from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.academics.models import Classroom, Enrollment, Student
from .forms import ExpenseForm, FeeChargeForm, FeePaymentForm, StaffMemberForm
from .models import (
    MONEY_ZERO,
    Expense,
    FeeCharge,
    FeePayment,
    FeeReminder,
    StaffMember,
    student_fee_totals,
)
from .services import (
    class_summaries,
    generate_monthly_fees,
    last_monthly_fee,
    money_summary,
    month_start,
    reminder_message,
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
            created, skipped, total = generate_monthly_fees(month, due_day, amounts, request.user)
            note = f" {skipped} student{'s were' if skipped != 1 else ' was'} already billed and skipped." if skipped else ""
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
    paid_ids = set(
        Expense.objects.filter(salary_month=month, staff__isnull=False).values_list("staff_id", flat=True)
    )
    staff = list(StaffMember.objects.order_by("-is_active", "name"))
    for member in staff:
        member.paid_this_month = member.pk in paid_ids
    return render(
        request,
        "fees/staff.html",
        {"staff": staff, "money": money_summary(timezone.localdate()), "month": month},
    )


@login_required
def staff_form(request, staff_id=None):
    _require_fee_staff(request.user)
    member = get_object_or_404(StaffMember, pk=staff_id) if staff_id else None
    form = StaffMemberForm(request.POST or None, instance=member)
    if request.method == "POST" and form.is_valid():
        member = form.save()
        messages.success(request, f"{member.name} saved.")
        return redirect("fees:staff")
    return render(request, "fees/staff_form.html", {"form": form, "member": member})


@login_required
@require_POST
def staff_pay(request, staff_id):
    _require_fee_staff(request.user)
    member = get_object_or_404(StaffMember, pk=staff_id, is_active=True)
    today = timezone.localdate()
    month = month_start(today)
    if member.monthly_salary <= 0:
        messages.error(request, f"Set a salary for {member.name} first.")
        return redirect("fees:staff")
    try:
        with transaction.atomic():
            Expense.objects.create(
                category=Expense.Category.SALARY,
                description=f"Salary — {member.name} — {month:%B %Y}",
                amount=member.monthly_salary,
                date=today,
                staff=member,
                salary_month=month,
                recorded_by=request.user,
            )
    except IntegrityError:
        messages.info(request, f"{member.name}'s salary for {month:%B} is already paid.")
    else:
        messages.success(request, f"Salary paid to {member.name} for {month:%B %Y}.")
    return redirect("fees:staff")


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
