from decimal import Decimal
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone


MONEY_ZERO = Decimal("0.00")


class FeeCharge(models.Model):
    class Category(models.TextChoices):
        MONTHLY = "monthly", "Monthly fee"
        ADMISSION = "admission", "Admission fee"
        ANNUAL = "annual", "Annual fund"
        EXAM = "exam", "Exam fee"
        LATE_FEE = "late_fee", "Late fee fine"
        LAB = "lab", "Lab charges"
        ACTIVITY = "activity", "Activity charges"
        OTHER = "other", "Other"

    student = models.ForeignKey(
        "academics.Student", on_delete=models.PROTECT, related_name="fee_charges"
    )
    academic_year = models.ForeignKey(
        "academics.AcademicYear",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fee_charges",
    )
    enrollment = models.ForeignKey(
        "academics.Enrollment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fee_charges",
    )
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.MONTHLY)
    description = models.CharField(max_length=160)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    due_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_fee_charges",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("due_date", "id")
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="fees_charge_amount_positive"),
        ]

    def __str__(self):
        return f"{self.student} — {self.description} ({self.amount})"

    def clean(self):
        super().clean()
        if self.enrollment_id:
            if self.enrollment.student_id != self.student_id:
                raise ValidationError({"enrollment": "Enrollment must belong to this student."})
            if self.academic_year_id and self.enrollment.academic_year_id != self.academic_year_id:
                raise ValidationError({"enrollment": "Enrollment must belong to the selected academic year."})
            if not self.academic_year_id:
                self.academic_year_id = self.enrollment.academic_year_id

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)


class FeePaymentQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Payments are immutable and cannot be edited.")

    def delete(self):
        raise ValidationError("Payments cannot be deleted.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Payments are immutable and cannot be edited.")


class FeePayment(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Cash"
        BANK_TRANSFER = "bank_transfer", "Bank transfer"
        MOBILE_MONEY = "mobile_money", "Mobile money"
        CARD = "card", "Card"
        CHEQUE = "cheque", "Cheque"
        OTHER = "other", "Other"

    student = models.ForeignKey(
        "academics.Student", on_delete=models.PROTECT, related_name="fee_payments"
    )
    academic_year = models.ForeignKey(
        "academics.AcademicYear",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fee_payments",
    )
    enrollment = models.ForeignKey(
        "academics.Enrollment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="fee_payments",
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    payment_date = models.DateField(default=timezone.localdate)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.CASH)
    receipt_reference = models.CharField(max_length=40, unique=True, blank=True)
    notes = models.CharField(max_length=240, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="received_fee_payments",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    objects = FeePaymentQuerySet.as_manager()

    class Meta:
        ordering = ("-payment_date", "-id")
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="fees_payment_amount_positive"),
            models.CheckConstraint(
                condition=models.Q(
                    method__in=("cash", "bank_transfer", "mobile_money", "card", "cheque", "other")
                ),
                name="fees_payment_method_valid",
            ),
        ]

    def __str__(self):
        return f"{self.receipt_reference or 'New receipt'} — {self.student} ({self.amount})"

    def clean(self):
        super().clean()
        if self.enrollment_id:
            if self.enrollment.student_id != self.student_id:
                raise ValidationError({"enrollment": "Enrollment must belong to this student."})
            if self.academic_year_id and self.enrollment.academic_year_id != self.academic_year_id:
                raise ValidationError({"enrollment": "Enrollment must belong to the selected academic year."})
            if not self.academic_year_id:
                self.academic_year_id = self.enrollment.academic_year_id

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Payments are immutable and cannot be edited.")
        if not self.receipt_reference:
            self.receipt_reference = f"FEE-{uuid4().hex.upper()}"
        self.clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Payments cannot be deleted.")


def student_fee_totals(student, academic_year=None):
    """Return charged, paid, and outstanding Decimal amounts for one student."""
    charges = FeeCharge.objects.filter(student=student)
    payments = FeePayment.objects.filter(student=student)
    if academic_year is not None:
        charges = charges.filter(academic_year=academic_year)
        payments = payments.filter(academic_year=academic_year)
    charged = charges.aggregate(total=Sum("amount"))["total"] or MONEY_ZERO
    paid = payments.aggregate(total=Sum("amount"))["total"] or MONEY_ZERO
    return {"charged": charged, "paid": paid, "outstanding": charged - paid}


class StaffMember(models.Model):
    """Anyone the school pays a salary to, with or without a login."""

    name = models.CharField(max_length=120)
    designation = models.CharField(max_length=80, help_text="For example: Teacher, Accountant, Guard.")
    phone = models.CharField(max_length=30, blank=True)
    monthly_salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff_profile",
    )
    joined_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.CheckConstraint(condition=models.Q(monthly_salary__gte=0), name="fees_staff_salary_not_negative"),
        ]

    def __str__(self):
        return f"{self.name} ({self.designation})"


class Expense(models.Model):
    class Category(models.TextChoices):
        SALARY = "salary", "Salary"
        ADVANCE = "advance", "Salary advance"
        UTILITIES = "utilities", "Utility bills"
        RENT = "rent", "Rent"
        SUPPLIES = "supplies", "Stationery & supplies"
        MAINTENANCE = "maintenance", "Repairs & maintenance"
        OTHER = "other", "Other"

    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    description = models.CharField(max_length=160)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    date = models.DateField(default=timezone.localdate)
    staff = models.ForeignKey(
        StaffMember,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="salary_payments",
    )
    salary_month = models.DateField(
        null=True,
        blank=True,
        help_text="First day of the month this salary is for.",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recorded_expenses",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-date", "-id")
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="fees_expense_amount_positive"),
            models.UniqueConstraint(
                fields=("staff", "salary_month"),
                condition=models.Q(staff__isnull=False),
                name="fees_one_salary_per_staff_month",
            ),
        ]

    def __str__(self):
        return f"{self.date} — {self.description} ({self.amount})"


class FeeReminder(models.Model):
    """A log of fee reminders sent to a student's guardian."""

    student = models.ForeignKey(
        "academics.Student", on_delete=models.CASCADE, related_name="fee_reminders"
    )
    amount_due = models.DecimalField(max_digits=10, decimal_places=2)
    phone = models.CharField(max_length=30)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_fee_reminders",
    )
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-sent_at",)

    def __str__(self):
        return f"Reminder to {self.student} ({self.amount_due})"


class FeeConcession(models.Model):
    """A standing discount on a student's monthly tuition fee."""

    student = models.OneToOneField(
        "academics.Student", on_delete=models.CASCADE, related_name="fee_concession"
    )
    percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(Decimal("100"))],
        help_text="100 means the monthly fee is fully waived.",
    )
    reason = models.CharField(max_length=160, help_text="For example: sibling discount, staff child, need-based.")
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_fee_concessions",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(percent__gt=0) & models.Q(percent__lte=100),
                name="fees_concession_percent_range",
            ),
        ]

    def __str__(self):
        return f"{self.student}: {self.percent}% ({self.reason})"

    def apply(self, amount):
        """The fee after this concession, rounded to whole rupees."""
        return (amount * (Decimal("100") - self.percent) / Decimal("100")).quantize(Decimal("1"))


class StaffAttendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        ABSENT = "absent", "Absent"
        LATE = "late", "Late"
        LEAVE = "leave", "On leave"

    staff = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name="attendance")
    date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PRESENT)
    note = models.CharField(max_length=160, blank=True, help_text="Reason for leave or absence.")
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-date", "staff__name")
        constraints = [
            models.UniqueConstraint(fields=("staff", "date"), name="fees_one_staff_attendance_per_day")
        ]

    def __str__(self):
        return f"{self.staff.name} {self.date}: {self.get_status_display()}"


class SalarySlip(models.Model):
    """The breakdown behind one salary payment (the Expense holds the net amount paid)."""

    expense = models.OneToOneField(Expense, on_delete=models.CASCADE, related_name="slip")
    basic = models.DecimalField(max_digits=10, decimal_places=2)
    allowance = models.DecimalField(max_digits=10, decimal_places=2, default=MONEY_ZERO)
    absent_days = models.PositiveSmallIntegerField(default=0)
    absence_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=MONEY_ZERO)
    advance_recovered = models.DecimalField(max_digits=10, decimal_places=2, default=MONEY_ZERO)
    other_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=MONEY_ZERO)
    note = models.CharField(max_length=200, blank=True)

    def __str__(self):
        return f"Slip for {self.expense}"

    @property
    def total_deductions(self):
        return self.absence_deduction + self.advance_recovered + self.other_deduction
