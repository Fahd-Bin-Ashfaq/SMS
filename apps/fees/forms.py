from decimal import Decimal

from django import forms
from django.db.models import Sum

from apps.academics.models import AcademicYear, Enrollment, Student
from .models import Expense, FeeCharge, FeePayment, MONEY_ZERO, StaffMember


class FeeChargeForm(forms.ModelForm):
    class Meta:
        model = FeeCharge
        fields = ("student", "academic_year", "enrollment", "category", "description", "amount", "due_date")
        widgets = {"due_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["student"].queryset = Student.objects.order_by("last_name", "first_name")
        self.fields["academic_year"].queryset = AcademicYear.objects.order_by("-start_date")
        self.fields["enrollment"].queryset = Enrollment.objects.select_related(
            "student", "academic_year"
        ).order_by("-academic_year__start_date", "student__last_name")

    def clean(self):
        cleaned = super().clean()
        student, year, enrollment = (
            cleaned.get("student"),
            cleaned.get("academic_year"),
            cleaned.get("enrollment"),
        )
        if enrollment and student and enrollment.student_id != student.pk:
            self.add_error("enrollment", "Choose an enrollment for the selected student.")
        if enrollment and year and enrollment.academic_year_id != year.pk:
            self.add_error("enrollment", "Choose an enrollment in the selected academic year.")
        return cleaned


class FeePaymentForm(forms.ModelForm):
    class Meta:
        model = FeePayment
        fields = (
            "student",
            "academic_year",
            "enrollment",
            "amount",
            "payment_date",
            "method",
            "receipt_reference",
            "notes",
        )
        widgets = {"payment_date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["student"].queryset = Student.objects.order_by("last_name", "first_name")
        self.fields["academic_year"].queryset = AcademicYear.objects.order_by("-start_date")
        self.fields["enrollment"].queryset = Enrollment.objects.select_related(
            "student", "academic_year"
        ).order_by("-academic_year__start_date", "student__last_name")
        self.fields["receipt_reference"].required = False
        self.fields["receipt_reference"].help_text = "Leave blank to generate a unique receipt number."

    def clean(self):
        cleaned = super().clean()
        student, year, enrollment = (
            cleaned.get("student"),
            cleaned.get("academic_year"),
            cleaned.get("enrollment"),
        )
        if enrollment and student and enrollment.student_id != student.pk:
            self.add_error("enrollment", "Choose an enrollment for the selected student.")
        if enrollment and year and enrollment.academic_year_id != year.pk:
            self.add_error("enrollment", "Choose an enrollment in the selected academic year.")
        amount = cleaned.get("amount")
        if student and amount and amount > Decimal("0.00"):
            charges = FeeCharge.objects.filter(student=student)
            payments = FeePayment.objects.filter(student=student)
            if year:
                charges = charges.filter(academic_year=year)
                payments = payments.filter(academic_year=year)
            charged = charges.aggregate(total=Sum("amount"))["total"] or MONEY_ZERO
            paid = payments.aggregate(total=Sum("amount"))["total"] or MONEY_ZERO
            if amount > charged - paid:
                self.add_error("amount", "Payment cannot exceed the student's outstanding fees.")
        return cleaned


class StaffMemberForm(forms.ModelForm):
    class Meta:
        model = StaffMember
        fields = ("name", "designation", "phone", "monthly_salary", "joined_on", "is_active")
        widgets = {"joined_on": forms.DateInput(attrs={"type": "date"})}
        labels = {"monthly_salary": "Monthly salary (Rs)", "is_active": "Currently working here"}


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ("category", "description", "amount", "date")
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}
        labels = {"amount": "Amount (Rs)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Salaries are paid from the staff page so each month is recorded once per person.
        self.fields["category"].choices = [
            choice for choice in Expense.Category.choices if choice[0] != Expense.Category.SALARY
        ]
