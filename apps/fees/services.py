import re
from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

from django.conf import settings
from django.db import transaction
from django.db.models import Max, Q, Sum

from apps.academics.models import Enrollment
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
)


def _totals_by_student(queryset):
    return dict(
        queryset.values("student_id").annotate(total=Sum("amount")).values_list("student_id", "total")
    )


def student_balances(today, classroom=None, student=None):
    """One row per actively enrolled student with the fee amount due by today.

    Only charges whose due date has arrived count as due, so a month billed in
    advance does not show up as a debt. Payments are applied to the total.
    """
    enrollments = Enrollment.objects.filter(
        status=Enrollment.Status.ACTIVE,
        academic_year__is_active=True,
        student__is_active=True,
    ).select_related("student", "classroom")
    if classroom is not None:
        enrollments = enrollments.filter(classroom=classroom)
    if student is not None:
        enrollments = enrollments.filter(student=student)
    enrollments = list(enrollments)
    student_ids = [enrollment.student_id for enrollment in enrollments]

    charged = _totals_by_student(
        FeeCharge.objects.filter(student_id__in=student_ids).filter(
            Q(due_date__isnull=True) | Q(due_date__lte=today)
        )
    )
    paid = _totals_by_student(FeePayment.objects.filter(student_id__in=student_ids))
    reminded = dict(
        FeeReminder.objects.filter(student_id__in=student_ids)
        .values("student_id")
        .annotate(last=Max("sent_at"))
        .values_list("student_id", "last")
    )

    rows = []
    for enrollment in enrollments:
        student_id = enrollment.student_id
        due = charged.get(student_id, MONEY_ZERO) - paid.get(student_id, MONEY_ZERO)
        rows.append(
            {
                "student": enrollment.student,
                "classroom": enrollment.classroom,
                "due": max(due, MONEY_ZERO),
                "paid": paid.get(student_id, MONEY_ZERO),
                "last_reminder": reminded.get(student_id),
            }
        )
    rows.sort(
        key=lambda row: (
            row["classroom"].name,
            row["classroom"].section,
            row["student"].first_name,
            row["student"].last_name,
        )
    )
    return rows


def class_summaries(rows):
    """Group student balance rows by class."""
    summaries = {}
    for row in rows:
        classroom = row["classroom"]
        summary = summaries.setdefault(
            classroom.pk,
            {"classroom": classroom, "students": 0, "paid": 0, "due": 0, "due_amount": MONEY_ZERO},
        )
        summary["students"] += 1
        if row["due"] > 0:
            summary["due"] += 1
            summary["due_amount"] += row["due"]
        else:
            summary["paid"] += 1
    return list(summaries.values())


def month_start(day):
    return day.replace(day=1)


def monthly_fee_label(month):
    return f"Tuition fee — {month:%B %Y}"


def last_monthly_fee(classroom):
    """The most recent monthly fee charged to anyone in this class, if any."""
    charge = (
        FeeCharge.objects.filter(category=FeeCharge.Category.MONTHLY, enrollment__classroom=classroom)
        .order_by("-due_date", "-pk")
        .first()
    )
    return charge.amount if charge else None


def generate_monthly_fees(month, due_day, amounts, user):
    """Bill one month's tuition to every active student in the given classes.

    ``amounts`` maps classroom pk to the fee for that class. A student who already
    has a monthly charge due in that month is skipped, so running it twice is safe.
    A student's concession lowers their fee; a 100% concession bills nothing.
    Returns (created_count, skipped_count, total_amount, waived_count).
    """
    due_date = month.replace(day=min(due_day, 28))
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    enrollments = Enrollment.objects.filter(
        classroom_id__in=amounts,
        status=Enrollment.Status.ACTIVE,
        academic_year__is_active=True,
        student__is_active=True,
    ).select_related("academic_year")
    already_billed = set(
        FeeCharge.objects.filter(
            category=FeeCharge.Category.MONTHLY,
            due_date__gte=month,
            due_date__lt=next_month,
            student_id__in=enrollments.values("student_id"),
        ).values_list("student_id", flat=True)
    )
    concessions = {
        c.student_id: c for c in FeeConcession.objects.filter(student_id__in=enrollments.values("student_id"))
    }
    created, skipped, total, waived = 0, 0, MONEY_ZERO, 0
    with transaction.atomic():
        for enrollment in enrollments:
            if enrollment.student_id in already_billed:
                skipped += 1
                continue
            amount = amounts[enrollment.classroom_id]
            concession = concessions.get(enrollment.student_id)
            if concession is not None:
                amount = concession.apply(amount)
                if amount <= 0:
                    waived += 1
                    continue
            FeeCharge.objects.create(
                student_id=enrollment.student_id,
                enrollment=enrollment,
                academic_year=enrollment.academic_year,
                category=FeeCharge.Category.MONTHLY,
                description=monthly_fee_label(month),
                amount=amount,
                due_date=due_date,
                created_by=user,
            )
            created += 1
            total += amount
    return created, skipped, total, waived


def bulk_charge(classroom_ids, category, description, amount, due_date, user):
    """Add one charge (admission fee, annual fund, exam fee...) to every active
    student in the given classes. A student who already has a charge with the
    same description is skipped. Returns (created_count, skipped_count)."""
    enrollments = Enrollment.objects.filter(
        classroom_id__in=classroom_ids,
        status=Enrollment.Status.ACTIVE,
        academic_year__is_active=True,
        student__is_active=True,
    ).select_related("academic_year")
    existing = set(
        FeeCharge.objects.filter(
            description=description, student_id__in=enrollments.values("student_id")
        ).values_list("student_id", flat=True)
    )
    created = skipped = 0
    with transaction.atomic():
        for enrollment in enrollments:
            if enrollment.student_id in existing:
                skipped += 1
                continue
            FeeCharge.objects.create(
                student_id=enrollment.student_id,
                enrollment=enrollment,
                academic_year=enrollment.academic_year,
                category=category,
                description=description,
                amount=amount,
                due_date=due_date,
                created_by=user,
            )
            created += 1
    return created, skipped


def late_fee_label(month):
    return f"Late fee — {month:%B %Y}"


def apply_late_fees(month, amount, today, user):
    """Fine students whose monthly fee for ``month`` is past due and still unpaid.

    Each student is fined at most once per month. Returns (fined_count, already_fined_count).
    """
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    late_charges = FeeCharge.objects.filter(
        category=FeeCharge.Category.MONTHLY,
        due_date__gte=month,
        due_date__lt=min(next_month, today),
    ).select_related("enrollment__academic_year")
    owing = {row["student"].pk for row in student_balances(today) if row["due"] > 0}
    label = late_fee_label(month)
    already = set(FeeCharge.objects.filter(description=label).values_list("student_id", flat=True))
    fined = skipped = 0
    with transaction.atomic():
        for charge in late_charges:
            if charge.student_id not in owing:
                continue
            if charge.student_id in already:
                skipped += 1
                continue
            FeeCharge.objects.create(
                student_id=charge.student_id,
                enrollment=charge.enrollment,
                academic_year=charge.academic_year,
                category=FeeCharge.Category.LATE_FEE,
                description=label,
                amount=amount,
                due_date=today,
                created_by=user,
            )
            already.add(charge.student_id)
            fined += 1
    return fined, skipped


def money_summary(today):
    """Income, expenses and staff figures for the current month."""
    start = month_start(today)
    collected = (
        FeePayment.objects.filter(payment_date__gte=start, payment_date__lte=today)
        .aggregate(total=Sum("amount"))["total"]
        or MONEY_ZERO
    )
    expenses = Expense.objects.filter(date__gte=start, date__lte=today)
    spent = expenses.aggregate(total=Sum("amount"))["total"] or MONEY_ZERO
    staff = StaffMember.objects.filter(is_active=True)
    salary_bill = staff.aggregate(total=Sum("monthly_salary"))["total"] or MONEY_ZERO
    salary_paid = (
        Expense.objects.filter(category=Expense.Category.SALARY, salary_month=start)
        .aggregate(total=Sum("amount"))["total"]
        or MONEY_ZERO
    )
    return {
        "month": start,
        "collected": collected,
        "spent": spent,
        "net": collected - spent,
        "staff_count": staff.count(),
        "salary_bill": salary_bill,
        "salary_paid": salary_paid,
        "salary_remaining": max(salary_bill - salary_paid, MONEY_ZERO),
    }


def whatsapp_number(raw):
    """Turn a Pakistani phone number such as 0300-1234567 into 923001234567."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) == 11:
        digits = "92" + digits[1:]
    return digits if len(digits) >= 11 else ""


def reminder_message(student, classroom, amount):
    guardian = student.guardian_name or "Parent"
    return (
        f"Assalam-o-Alaikum {guardian}, "
        f"{student.first_name} {student.last_name} ({classroom.name} {classroom.section}) "
        f"ki school fee Rs {amount:,.0f} baqi hai. "
        f"Meharbani farma kar jald ada karein. Shukriya — {settings.SCHOOL_NAME}"
    )


def whatsapp_link(phone, message):
    return f"https://wa.me/{phone}?text={quote(message)}"


def advance_outstanding(member):
    """Advances paid to a staff member that later salaries have not recovered yet."""
    given = (
        Expense.objects.filter(staff=member, category=Expense.Category.ADVANCE).aggregate(total=Sum("amount"))["total"]
        or MONEY_ZERO
    )
    recovered = (
        SalarySlip.objects.filter(expense__staff=member).aggregate(total=Sum("advance_recovered"))["total"]
        or MONEY_ZERO
    )
    return max(given - recovered, MONEY_ZERO)


def salary_suggestion(member, month):
    """Pre-filled salary slip: full salary less one day's pay per absence (a month counts as 30 days)."""
    next_month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    absent = StaffAttendance.objects.filter(
        staff=member, date__gte=month, date__lt=next_month, status=StaffAttendance.Status.ABSENT
    ).count()
    per_day = member.monthly_salary / Decimal("30")
    return {
        "basic": member.monthly_salary,
        "allowance": MONEY_ZERO,
        "absent_days": absent,
        "absence_deduction": (per_day * absent).quantize(Decimal("1")),
        "advance_recovered": min(advance_outstanding(member), member.monthly_salary),
        "other_deduction": MONEY_ZERO,
        "note": "",
    }
