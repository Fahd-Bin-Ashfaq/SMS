from datetime import date
from decimal import Decimal

from django import forms
from django.db.models import Sum

from apps.academics.models import AcademicYear, Enrollment, Student
from .models import Expense, FeeCharge, FeeConcession, FeePayment, MONEY_ZERO, StaffMember


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
        # Salaries and advances are paid from the staff page so they stay linked to the person.
        self.fields["category"].choices = [
            choice for choice in Expense.Category.choices
            if choice[0] not in (Expense.Category.SALARY, Expense.Category.ADVANCE)
        ]


class FeeConcessionForm(forms.ModelForm):
    class Meta:
        model = FeeConcession
        fields = ("percent", "reason")
        labels = {"percent": "Discount on monthly fee (%)"}


class BulkChargeForm(forms.Form):
    classrooms = forms.ModelMultipleChoiceField(
        queryset=None, widget=forms.CheckboxSelectMultiple, label="Classes"
    )
    category = forms.ChoiceField(
        choices=[
            choice for choice in FeeCharge.Category.choices
            if choice[0] not in (FeeCharge.Category.MONTHLY, FeeCharge.Category.LATE_FEE)
        ]
    )
    description = forms.CharField(max_length=160, help_text="Shown on the student's account, e.g. Annual fund 2026-2027.")
    amount = forms.DecimalField(label="Amount (Rs)", max_digits=10, decimal_places=2, min_value=Decimal("1"))
    due_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))

    def __init__(self, *args, classrooms, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["classrooms"].queryset = classrooms


class LateFeeForm(forms.Form):
    month = forms.CharField(
        widget=forms.DateInput(attrs={"type": "month"}),
        help_text="Students who still owe this month's fee after its due date are fined.",
    )
    amount = forms.DecimalField(label="Fine (Rs)", max_digits=10, decimal_places=2, min_value=Decimal("1"))

    def clean_month(self):
        try:
            year, number = (int(part) for part in self.cleaned_data["month"].split("-"))
            return date(year, number, 1)
        except ValueError:
            raise forms.ValidationError("Choose a month.")


class SalaryPaymentForm(forms.Form):
    basic = forms.DecimalField(label="Basic salary", max_digits=10, decimal_places=2, min_value=0)
    allowance = forms.DecimalField(label="Allowance / bonus", max_digits=10, decimal_places=2, min_value=0, required=False)
    absent_days = forms.IntegerField(min_value=0, max_value=31, required=False)
    absence_deduction = forms.DecimalField(label="Absence deduction", max_digits=10, decimal_places=2, min_value=0, required=False)
    advance_recovered = forms.DecimalField(label="Advance recovered", max_digits=10, decimal_places=2, min_value=0, required=False)
    other_deduction = forms.DecimalField(label="Other deduction", max_digits=10, decimal_places=2, min_value=0, required=False)
    note = forms.CharField(max_length=200, required=False)

    def __init__(self, *args, advance_limit=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.advance_limit = advance_limit

    def clean(self):
        cleaned = super().clean()
        for name in ("allowance", "absence_deduction", "advance_recovered", "other_deduction"):
            cleaned[name] = cleaned.get(name) or MONEY_ZERO
        cleaned["absent_days"] = cleaned.get("absent_days") or 0
        if self.advance_limit is not None and cleaned["advance_recovered"] > self.advance_limit:
            self.add_error("advance_recovered", f"Only Rs {self.advance_limit:,.0f} of advance is still owed.")
        if cleaned.get("basic") is not None and not self.errors:
            cleaned["net"] = (
                cleaned["basic"] + cleaned["allowance"]
                - cleaned["absence_deduction"] - cleaned["advance_recovered"] - cleaned["other_deduction"]
            )
            if cleaned["net"] <= 0:
                raise forms.ValidationError("The salary to pay must be more than zero.")
        return cleaned


class AdvanceForm(forms.Form):
    amount = forms.DecimalField(label="Advance (Rs)", max_digits=10, decimal_places=2, min_value=Decimal("1"))
    note = forms.CharField(max_length=120, required=False)
