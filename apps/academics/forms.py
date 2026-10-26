from django import forms

from .models import AcademicYear, Classroom, Student, Subject, Teacher, TimetableEntry


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
        fields = ("name", "section", "academic_year", "class_teacher")


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
            "gender",
            "cnic",
            "email",
            "phone",
            "address",
            "area",
            "is_active",
        )
        widgets = {"date_of_birth": forms.DateInput(attrs={"type": "date"})}


class TimetableEntryForm(forms.ModelForm):
    class Meta:
        model = TimetableEntry
        fields = ("day", "start_time", "end_time", "subject", "teacher", "label")
        widgets = {
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
        }

    def __init__(self, *args, classroom, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.classroom = classroom
        assignments = classroom.teacher_assignments.all()
        self.fields["subject"].queryset = Subject.objects.filter(
            pk__in=assignments.values("subject_id")
        )
        self.fields["teacher"].queryset = Teacher.objects.filter(
            pk__in=assignments.values("teacher_id")
        ).select_related("user")
