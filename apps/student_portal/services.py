from datetime import date

from django.db.models import Count, Q

from apps.attendance.models import AttendanceRecord
from apps.fees.models import MONEY_ZERO, FeeCharge, FeePayment


def attendance_summary(enrollment):
    counts = {"present": 0, "late": 0, "absent": 0}
    if enrollment is not None:
        rows = (
            AttendanceRecord.objects.filter(enrollment=enrollment)
            .values("status")
            .annotate(total=Count("pk"))
        )
        for row in rows:
            counts[row["status"]] = row["total"]
    total = sum(counts.values())
    attended = counts["present"] + counts["late"]
    return {
        **counts,
        "total": total,
        "percent": round(attended * 100 / total) if total else None,
    }


def _months(start, end):
    month = date(start.year, start.month, 1)
    while month <= end:
        yield month
        month = date(month.year + month.month // 12, month.month % 12 + 1, 1)


def _status(paid, amount, due_date, today):
    if paid >= amount:
        return "paid"
    if due_date is None or due_date <= today:
        return "partial" if paid > MONEY_ZERO else "due"
    return "upcoming"


def fee_overview(student, year, today):
    """Summarise a student's fees for one academic year.

    Payments are not tied to a specific charge, so they are applied to the
    oldest charges first. Months the office has not billed yet are shown as
    upcoming at the latest monthly fee.
    """
    charges = list(
        FeeCharge.objects.filter(student=student, academic_year=year).order_by("due_date", "pk")
    )
    payments = list(
        FeePayment.objects.filter(student=student, academic_year=year).order_by("-payment_date", "-pk")
    )
    paid_total = sum((payment.amount for payment in payments), MONEY_ZERO)

    remaining = paid_total
    rows = []
    for charge in charges:
        paid = min(remaining, charge.amount)
        remaining -= paid
        rows.append(
            {
                "charge": charge,
                "amount": charge.amount,
                "paid": paid,
                "balance": charge.amount - paid,
                "status": _status(paid, charge.amount, charge.due_date, today),
            }
        )

    monthly = [row for row in rows if row["charge"].category == FeeCharge.Category.MONTHLY]
    other = [row for row in rows if row["charge"].category != FeeCharge.Category.MONTHLY]
    by_month = {}
    for row in monthly:
        due = row["charge"].due_date
        if due is not None:
            by_month.setdefault(date(due.year, due.month, 1), row)
    monthly_fee = monthly[-1]["amount"] if monthly else None

    months = []
    shown = set()
    for month in _months(year.start_date, year.end_date):
        row = by_month.get(month)
        if row is not None:
            shown.add(id(row))
            months.append({"month": month, **row})
        elif monthly_fee is not None and month > date(today.year, today.month, 1):
            months.append(
                {
                    "month": month,
                    "charge": None,
                    "amount": monthly_fee,
                    "paid": MONEY_ZERO,
                    "balance": monthly_fee,
                    "status": "upcoming",
                }
            )

    billed_outside_months = [row for row in monthly if id(row) not in shown]
    year_total = sum((row["amount"] for row in months + other + billed_outside_months), MONEY_ZERO)
    due_now = sum(
        (row["balance"] for row in rows if row["status"] in ("due", "partial")),
        MONEY_ZERO,
    )
    return {
        "months": months,
        "other_charges": other + billed_outside_months,
        "payments": payments,
        "year_total": year_total,
        "paid": paid_total,
        "due_now": due_now,
        "remaining": max(year_total - paid_total, MONEY_ZERO),
        "paid_months": sum(1 for row in months if row["status"] == "paid"),
        "advance": remaining,
    }


def notifications_for(classroom):
    from .models import Notification

    query = Q(classroom__isnull=True)
    if classroom is not None:
        query |= Q(classroom=classroom)
    return Notification.objects.filter(query)
