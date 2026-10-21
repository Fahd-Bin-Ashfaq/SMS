from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render

from apps.academics.models import Student
from .forms import FeeChargeForm, FeePaymentForm
from .models import FeeCharge, FeePayment, MONEY_ZERO, student_fee_totals


def _require_fee_staff(user):
    if not user.is_authenticated or getattr(user, "role", None) not in {"office", "principal"}:
        raise PermissionDenied


@login_required
def dues(request):
    _require_fee_staff(request.user)
    students = Student.objects.filter(
        fee_charges__isnull=False
    ).distinct().order_by("last_name", "first_name")
    student_ids = students.values_list("pk", flat=True)
    charged_by_student = dict(
        FeeCharge.objects.filter(student_id__in=student_ids)
        .values("student_id")
        .annotate(total=Sum("amount"))
        .values_list("student_id", "total")
    )
    paid_by_student = dict(
        FeePayment.objects.filter(student_id__in=student_ids)
        .values("student_id")
        .annotate(total=Sum("amount"))
        .values_list("student_id", "total")
    )
    rows = []
    for student in students:
        charged = charged_by_student.get(student.pk, MONEY_ZERO)
        paid = paid_by_student.get(student.pk, MONEY_ZERO)
        totals = {"charged": charged, "paid": paid, "outstanding": charged - paid}
        if totals["outstanding"] > Decimal("0.00"):
            rows.append({"student": student, **totals})
    return render(request, "fees/dues.html", {"rows": rows})


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
    form = FeePaymentForm(request.POST or None)
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
        FeePayment.objects.select_related("student", "academic_year", "received_by"),
        pk=payment_id,
    )
    return render(request, "fees/receipt.html", {"payment": payment})
