from django import forms

from .models import AcademicYear, Classroom, Student


class AcademicYearForm(forms.ModelForm):
    class Meta:
        model = AcademicYear
        fields = ("name", "start_date", "end_date", "is_active")
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


class ClassroomForm(forms.ModelForm):
    class Meta:
        model = Classroom
        fields = ("name", "section", "academic_year")


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = (
            "admission_number",
            "first_name",
            "last_name",
            "date_of_birth",
            "guardian_name",
            "guardian_phone",
            "is_active",
        )
        widgets = {"date_of_birth": forms.DateInput(attrs={"type": "date"})}
