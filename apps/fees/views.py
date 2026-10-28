from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.academics.models import Classroom, Enrollment, Student
from apps.accounts.credentials import (
    new_password,
    phone_username,
    pop_credentials,
    remember_credentials,
    unique_username,
)
from .forms import (
    AdvanceForm,
    BulkChargeForm,
    ExpenseForm,
    FeeChargeForm,
    FeeConcessionForm,
    FeePaymentForm,
    LateFeeForm,
    SalaryPaymentForm,
    StaffMemberForm,
)
from .models import (
    MONEY_ZERO,
    Expense,
    FeeCharge,
    FeeConcession,
    FeePayment,
    FeeReminder,
    SalarySlip,
    StaffAttendance,
    StaffMember,
    student_fee_totals,
)
from .services import (
    advance_outstanding,
    apply_late_fees,
    bulk_charge,
    class_summaries,
    generate_monthly_fees,
    last_monthly_fee,
    money_summary,
    month_start,
    reminder_message,
    salary_suggestion,
    student_balances,
    whatsapp_link,
    whatsapp_number,
)


def _require_fee_staff(user):
    if not user.is_authenticated or getattr(user, "role", None) not in {"office", "principal"}:
        raise PermissionDenied


def _back_to_dues(request):
    target = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect("fees:dues")


@login_required
def overview(request):
    _require_fee_staff(request.user)
    today = timezone.localdate()
    rows = student_balances(today)
    due_rows = [row for row in rows if row["due"] > 0]
    return render(
        request,
        "fees/overview.html",
        {
            "today": today,
            "total_students": len(rows),
            "due_students": len(due_rows),
            "total_due": sum((row["due"] for row in due_rows), MONEY_ZERO),
            "classes": class_summaries(rows),
            "money": money_summary(today),
        },
    )


@login_required
def dues(request):
    _require_fee_staff(request.user)
    today = timezone.localdate()
    classrooms = Classroom.objects.filter(academic_year__is_active=True).order_by("name", "section")
    selected = next((c for c in classrooms if str(c.pk) == request.GET.get("class")), None)
    show = request.GET.get("show", "due")
    if show not in {"due", "paid", "all"}:
        show = "due"
    all_rows = student_balances(today, classroom=selected)
    rows = [
        row for row in all_rows
        if show == "all" or (show == "due") == (row["due"] > 0)
    ]
    for row in rows:
        row["phone"] = row["student"].guardian_phone or row["student"].phone
        row["can_remind"] = row["due"] > 0 and bool(whatsapp_number(row["phone"]))
    return render(
        request,
        "fees/dues.html",
        {
            "rows": rows,
            "classrooms": classrooms,
            "selected_class": selected,
            "show": show,
            "due_count": sum(1 for row in all_rows if row["due"] > 0),
            "paid_count": sum(1 for row in all_rows if row["due"] == 0),
            "all_count": len(all_rows),
            "shown_due": sum((row["due"] for row in rows), MONEY_ZERO),
        },
    )


def _parse_month(value, default):
    try:
        year, number = (int(part) for part in value.split("-"))
        return date(year, number, 1)
    except (AttributeError, ValueError):
        return default


@login_required
def generate_fees(request):
    _require_fee_staff(request.user)
    today = timezone.localdate()
    classrooms = list(
        Classroom.objects.filter(academic_year__is_active=True)
        .annotate(
            student_count=Count(
                "enrollments",
                filter=Q(enrollments__status=Enrollment.Status.ACTIVE, enrollments__student__is_active=True),
            )
        )
        .order_by("name", "section")
    )
    source = request.POST if request.method == "POST" else None
    month = _parse_month(source.get("month") if source else request.GET.get("month"), month_start(today))
    due_day = 10
    errors = []
    if source:
        try:
            due_day = int(source.get("due_day", ""))
            if not 1 <= due_day <= 28:
                raise ValueError
        except ValueError:
            errors.append("Due day must be a number from 1 to 28.")
    amounts = {}
    for classroom in classrooms:
        raw = (source.get(f"amount_{classroom.pk}", "") if source else "").replace(",", "").strip()
        if source:
            classroom.fee_input = raw
        else:
            fee = last_monthly_fee(classroom)
            classroom.fee_input = f"{fee:f}".removesuffix(".00") if fee else ""
        if source and raw:
            try:
                amount = Decimal(raw)
                if amount <= 0:
                    raise InvalidOperation
                amounts[classroom.pk] = amount.quantize(Decimal("0.01"))
            except InvalidOperation:
                errors.append(f"Enter a valid fee for {classroom.name} {classroom.section}.")
    if source and not errors:
        if not amounts:
            errors.append("Enter the monthly fee for at least one class.")
        else:
            created, skipped, total, waived = generate_monthly_fees(month, due_day, amounts, request.user)
            note = f" {skipped} student{'s were' if skipped != 1 else ' was'} already billed and skipped." if skipped else ""
            if waived:
                note += f" {waived} with a full concession {'were' if waived != 1 else 'was'} not charged."
            messages.success(
                request,
                f"{month:%B %Y} fee added for {created} student{'s' if created != 1 else ''} "
                f"(total Rs {total:,.0f}).{note}",
            )
            return redirect("fees:dues")
    return render(
        request,
        "fees/generate.html",
        {"classrooms": classrooms, "month": month, "due_day": due_day, "errors": errors},
    )


@login_required
@require_POST
def remind(request, student_id):
    _require_fee_staff(request.user)
    student = get_object_or_404(Student, pk=student_id)
    rows = student_balances(timezone.localdate(), student=student)
    if not rows or rows[0]["due"] <= 0:
        messages.info(request, f"{student.first_name} {student.last_name} has no fee due.")
        return _back_to_dues(request)
    row = rows[0]
    phone = whatsapp_number(student.guardian_phone or student.phone)
    if not phone:
        messages.error(request, f"No valid phone number for {student.first_name} {student.last_name}'s guardian.")
        return _back_to_dues(request)
    FeeReminder.objects.create(student=student, amount_due=row["due"], phone=phone, sent_by=request.user)
    return redirect(whatsapp_link(phone, reminder_message(student, row["classroom"], row["due"])))


@login_required
def staff_list(request):
    _require_fee_staff(request.user)
    month = month_start(timezone.localdate())
    paid = dict(
        Expense.objects.filter(salary_month=month, staff__isnull=False).values_list("staff_id", "pk")
    )
    staff = list(StaffMember.objects.select_related("user").order_by("-is_active", "name"))
    for member in staff:
        member.paid_this_month = member.pk in paid
        member.slip_id = paid.get(member.pk)
        member.advance_owed = advance_outstanding(member)
    return render(
        request,
        "fees/staff.html",
        {
            "staff": staff,
            "money": money_summary(timezone.localdate()),
            "month": month,
            "credentials": pop_credentials(request),
        },
    )


@login_required
@require_POST
def staff_login(request, staff_id):
    """Give a non-teaching staff member an office login (principal only)."""
    if getattr(request.user, "role", None) != "principal":
        raise PermissionDenied
    member = get_object_or_404(StaffMember, pk=staff_id, is_active=True)
    if member.user_id:
        messages.info(request, f"{member.name} already has a login.")
        return redirect("fees:staff")
    first, _, last = member.name.partition(" ")
    password = new_password()
    user = get_user_model().objects.create_user(
        username=unique_username(phone_username(member.phone), member.name.replace(" ", ".")),
        password=password,
        role="office",
        first_name=first,
        last_name=last,
    )
    member.user = user
    member.save(update_fields=["user"])
    remember_credentials(request, user=user, password=password, label=f"{member.name} (office)", send_to=member.phone)
    return redirect("fees:staff")


@login_required
def staff_form(request, staff_id=None):
    _require_fee_staff(request.user)
    member = get_object_or_404(StaffMember, pk=staff_id) if staff_id else None
    form = StaffMemberForm(request.POST or None, instance=member)
    if request.method == "POST" and form.is_valid():
        member = form.save()
        if (
            member.user_id
            and member.user.is_active != member.is_active
            and getattr(request.user, "role", None) == "principal"
            and member.user_id != request.user.pk
        ):
            # Someone who has left must not keep signing in. Only the principal
            # controls logins, so office staff cannot lock teachers out.
            member.user.is_active = member.is_active
            member.user.save(update_fields=["is_active"])
        messages.success(request, f"{member.name} saved.")
        return redirect("fees:staff")
    return render(request, "fees/staff_form.html", {"form": form, "member": member})


@login_required
def staff_pay(request, staff_id):
    """Pay this month's salary with allowance, absence and advance deductions."""
    _require_fee_staff(request.user)
    member = get_object_or_404(StaffMember, pk=staff_id, is_active=True)
    today = timezone.localdate()
    month = month_start(today)
    paid = Expense.objects.filter(staff=member, salary_month=month).first()
    if paid is not None:
        messages.info(request, f"{member.name}'s salary for {month:%B} is already paid.")
        return redirect("fees:salary-slip", expense_id=paid.pk)
    suggestion = salary_suggestion(member, month)
    outstanding = advance_outstanding(member)
    form = SalaryPaymentForm(request.POST or None, initial=suggestion, advance_limit=outstanding)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            with transaction.atomic():
                expense = Expense.objects.create(
                    category=Expense.Category.SALARY,
                    description=f"Salary — {member.name} — {month:%B %Y}",
                    amount=data["net"],
                    date=today,
                    staff=member,
                    salary_month=month,
                    recorded_by=request.user,
                )
                SalarySlip.objects.create(
                    expense=expense,
                    **{name: data[name] for name in (
                        "basic", "allowance", "absent_days", "absence_deduction",
                        "advance_recovered", "other_deduction", "note",
                    )},
                )
        except IntegrityError:
            messages.info(request, f"{member.name}'s salary for {month:%B} is already paid.")
            return redirect("fees:staff")
        messages.success(request, f"Salary of Rs {data['net']:,.0f} paid to {member.name} for {month:%B %Y}.")
        return redirect("fees:salary-slip", expense_id=expense.pk)
    return render(
        request,
        "fees/salary_pay.html",
        {"member": member, "month": month, "form": form, "outstanding": outstanding, "suggestion": suggestion},
    )


@login_required
def salary_slip(request, expense_id):
    _require_fee_staff(request.user)
    expense = get_object_or_404(
        Expense.objects.select_related("staff", "recorded_by"), pk=expense_id, category=Expense.Category.SALARY
    )
    return render(request, "fees/salary_slip.html", {"expense": expense, "slip": getattr(expense, "slip", None)})


@login_required
@require_POST
def staff_advance(request, staff_id):
    _require_fee_staff(request.user)
    member = get_object_or_404(StaffMember, pk=staff_id, is_active=True)
    form = AdvanceForm(request.POST)
    if form.is_valid():
        Expense.objects.create(
            category=Expense.Category.ADVANCE,
            description=f"Advance — {member.name}" + (f" — {form.cleaned_data['note']}" if form.cleaned_data["note"] else ""),
            amount=form.cleaned_data["amount"],
            staff=member,
            recorded_by=request.user,
        )
        messages.success(
            request,
            f"Advance of Rs {form.cleaned_data['amount']:,.0f} given to {member.name}. It will be suggested as a deduction on their next salary.",
        )
    else:
        messages.error(request, "Enter a valid advance amount.")
    return redirect("fees:staff")


@login_required
def staff_attendance(request):
    """Mark every working staff member present, absent, late or on leave for a day."""
    _require_fee_staff(request.user)
    today = timezone.localdate()
    try:
        day = date.fromisoformat(request.GET.get("date") or request.POST.get("date") or "")
    except ValueError:
        day = today
    if day > today:
        day = today
    members = list(StaffMember.objects.filter(is_active=True).order_by("name"))
    records = {r.staff_id: r for r in StaffAttendance.objects.filter(date=day, staff__in=members)}
    statuses = dict(StaffAttendance.Status.choices)
    if request.method == "POST":
        with transaction.atomic():
            for member in members:
                status = request.POST.get(f"status_{member.pk}", StaffAttendance.Status.PRESENT)
                if status not in statuses:
                    continue
                StaffAttendance.objects.update_or_create(
                    staff=member,
                    date=day,
                    defaults={
                        "status": status,
                        "note": request.POST.get(f"note_{member.pk}", "").strip()[:160],
                        "marked_by": request.user,
                    },
                )
        messages.success(request, f"Staff attendance saved for {day:%d %B %Y}.")
        return redirect(f"{reverse('fees:staff-attendance')}?date={day.isoformat()}")
    month = month_start(day)
    absences = dict(
        StaffAttendance.objects.filter(date__gte=month, date__lte=day, status=StaffAttendance.Status.ABSENT)
        .values("staff_id")
        .annotate(total=Count("pk"))
        .values_list("staff_id", "total")
    )
    leaves = dict(
        StaffAttendance.objects.filter(date__gte=month, date__lte=day, status=StaffAttendance.Status.LEAVE)
        .values("staff_id")
        .annotate(total=Count("pk"))
        .values_list("staff_id", "total")
    )
    for member in members:
        record = records.get(member.pk)
        member.today_status = record.status if record else StaffAttendance.Status.PRESENT
        member.today_note = record.note if record else ""
        member.month_absent = absences.get(member.pk, 0)
        member.month_leave = leaves.get(member.pk, 0)
    return render(
        request,
        "fees/staff_attendance.html",
        {
            "members": members,
            "day": day,
            "today": today,
            "saved": bool(records),
            "statuses": StaffAttendance.Status.choices,
            "month": month,
        },
    )


@login_required
def expenses(request):
    _require_fee_staff(request.user)
    today = timezone.localdate()
    month = month_start(today)
    try:
        year, number = (int(part) for part in request.GET.get("month", "").split("-"))
        month = date(year, number, 1)
    except ValueError:
        pass
    next_month = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    items = Expense.objects.filter(date__gte=month, date__lt=next_month).select_related("staff", "recorded_by")
    by_category = (
        items.values("category").annotate(total=Sum("amount")).order_by("-total")
    )
    labels = dict(Expense.Category.choices)
    collected = (
        FeePayment.objects.filter(payment_date__gte=month, payment_date__lt=next_month)
        .aggregate(total=Sum("amount"))["total"]
        or MONEY_ZERO
    )
    spent = items.aggregate(total=Sum("amount"))["total"] or MONEY_ZERO
    return render(
        request,
        "fees/expenses.html",
        {
            "items": items,
            "month": month,
            "previous_month": date(month.year - (month.month == 1), (month.month - 2) % 12 + 1, 1),
            "next_month": next_month if next_month <= today else None,
            "by_category": [{"label": labels[row["category"]], "total": row["total"]} for row in by_category],
            "collected": collected,
            "spent": spent,
            "net": collected - spent,
        },
    )


@login_required
def expense_create(request):
    _require_fee_staff(request.user)
    form = ExpenseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        expense = form.save(commit=False)
        expense.recorded_by = request.user
        expense.save()
        messages.success(request, "Expense recorded.")
        return redirect("fees:expenses")
    return render(request, "fees/expense_form.html", {"form": form})


@login_required
def student_account(request, student_id):
    _require_fee_staff(request.user)
    student = get_object_or_404(Student, pk=student_id)
    charges = FeeCharge.objects.filter(student=student).select_related("academic_year", "enrollment")
    payments = FeePayment.objects.filter(student=student).select_related("academic_year", "enrollment")
    return render(
        request,
        "fees/student_account.html",
        {
            "student": student,
            "charges": charges,
            "payments": payments,
            "totals": student_fee_totals(student),
            "concession": FeeConcession.objects.filter(student=student).select_related("approved_by").first(),
            "concession_form": FeeConcessionForm(),
            "can_set_concession": getattr(request.user, "role", None) == "principal",
        },
    )


@login_required
@require_POST
def concession(request, student_id):
    """Set or remove a student's monthly fee concession (principal only)."""
    if getattr(request.user, "role", None) != "principal":
        raise PermissionDenied
    student = get_object_or_404(Student, pk=student_id)
    if request.POST.get("action") == "remove":
        FeeConcession.objects.filter(student=student).delete()
        messages.success(request, f"Concession removed for {student.first_name}.")
    else:
        form = FeeConcessionForm(request.POST)
        if form.is_valid():
            FeeConcession.objects.update_or_create(
                student=student,
                defaults={**form.cleaned_data, "approved_by": request.user},
            )
            messages.success(
                request,
                f"{student.first_name} gets {form.cleaned_data['percent']:g}% off the monthly fee from the next bill.",
            )
        else:
            messages.error(request, " ".join(e for errors in form.errors.values() for e in errors))
    return redirect("fees:student-account", student_id=student.pk)


@login_required
def bulk_charges(request):
    """Charge an admission fee, annual fund, exam fee etc. to whole classes at once."""
    _require_fee_staff(request.user)
    classrooms = Classroom.objects.filter(academic_year__is_active=True).order_by("name", "section")
    form = BulkChargeForm(request.POST or None, classrooms=classrooms)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        created, skipped = bulk_charge(
            [c.pk for c in data["classrooms"]], data["category"], data["description"],
            data["amount"], data["due_date"], request.user,
        )
        note = f" {skipped} already had this charge and were skipped." if skipped else ""
        messages.success(request, f'"{data["description"]}" added for {created} students.{note}')
        return redirect("fees:dues")
    return render(request, "fees/bulk_charge.html", {"form": form})


@login_required
def late_fees(request):
    _require_fee_staff(request.user)
    today = timezone.localdate()
    form = LateFeeForm(request.POST or None, initial={"month": month_start(today).strftime("%Y-%m")})
    if request.method == "POST" and form.is_valid():
        fined, skipped = apply_late_fees(form.cleaned_data["month"], form.cleaned_data["amount"], today, request.user)
        month = form.cleaned_data["month"]
        if fined or skipped:
            note = f" {skipped} were already fined for {month:%B}." if skipped else ""
            messages.success(request, f"Late fee added for {fined} students who have not paid {month:%B %Y}.{note}")
        else:
            messages.info(request, f"Nobody to fine: everyone has paid {month:%B %Y}, or it is not past the due date yet.")
        return redirect("fees:dues")
    return render(request, "fees/late_fees.html", {"form": form})


@login_required
def daily_report(request):
    """Cash collected on one day, for closing the office in the evening."""
    _require_fee_staff(request.user)
    today = timezone.localdate()
    try:
        day = date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        day = today
    payments = list(
        FeePayment.objects.filter(payment_date=day)
        .select_related("student", "received_by", "enrollment__classroom")
        .order_by("created_at")
    )
    by_method, by_person = {}, {}
    for payment in payments:
        by_method[payment.get_method_display()] = by_method.get(payment.get_method_display(), MONEY_ZERO) + payment.amount
        person = payment.received_by.get_full_name() if payment.received_by else "—"
        by_person[person] = by_person.get(person, MONEY_ZERO) + payment.amount
    spent = Expense.objects.filter(date=day).aggregate(total=Sum("amount"))["total"] or MONEY_ZERO
    collected = sum((p.amount for p in payments), MONEY_ZERO)
    return render(
        request,
        "fees/daily_report.html",
        {
            "day": day,
            "today": today,
            "payments": payments,
            "by_method": sorted(by_method.items()),
            "by_person": sorted(by_person.items()),
            "collected": collected,
            "spent": spent,
            "cash_in_hand": collected - spent,
            "previous_day": day - timedelta(days=1),
            "next_day": day + timedelta(days=1) if day < today else None,
        },
    )


@login_required
def charge_create(request):
    _require_fee_staff(request.user)
    form = FeeChargeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        charge = form.save(commit=False)
        charge.created_by = request.user
        charge.save()
        messages.success(request, "Fee charge recorded.")
        return redirect("fees:student-account", student_id=charge.student_id)
    return render(request, "fees/charge_form.html", {"form": form})


@login_required
def payment_create(request):
    _require_fee_staff(request.user)
    form = FeePaymentForm(request.POST or None, initial={"student": request.GET.get("student")})
    if request.method == "POST" and form.is_valid():
        payment = form.save(commit=False)
        payment.received_by = request.user
        payment.save()
        messages.success(request, f"Payment recorded. Receipt {payment.receipt_reference}.")
        return redirect("fees:receipt", payment_id=payment.pk)
    return render(request, "fees/payment_form.html", {"form": form})


@login_required
def receipt(request, payment_id):
    _require_fee_staff(request.user)
    payment = get_object_or_404(
        FeePayment.objects.select_related("student", "academic_year", "received_by", "enrollment__classroom"),
        pk=payment_id,
    )
    balance = student_balances(timezone.localdate(), student=payment.student)
    classroom = payment.enrollment.classroom if payment.enrollment else (balance[0]["classroom"] if balance else None)
    return render(
        request,
        "fees/receipt.html",
        {
            "payment": payment,
            "classroom": classroom,
            "balance_due": balance[0]["due"] if balance else None,
            "copies": ("Parent copy", "School copy"),
        },
    )
