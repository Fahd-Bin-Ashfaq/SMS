from django import forms
from django.contrib.auth import get_user_model

from .models import AcademicYear, Classroom, Enrollment, Student, Subject, Teacher, TimetableEntry


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

    classroom = forms.ModelChoiceField(
        queryset=Classroom.objects.none(),
        label="Class",
        help_text="The class this student studies in this academic year.",
    )
    create_login = forms.BooleanField(
        required=False,
        label="Create a student portal login",
        help_text="Username is the admission number. The password is shown once and can be sent to the guardian on WhatsApp.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.year = AcademicYear.objects.filter(is_active=True).first()
        self.fields["classroom"].queryset = Classroom.objects.filter(academic_year=self.year).order_by("name", "section")
        if self.year is None:
            self.fields["classroom"].required = False
            self.fields["classroom"].help_text = "Set an active academic year to place students in a class."
        if self.instance.pk:
            enrollment = self.instance.enrollments.filter(academic_year=self.year).first()
            if enrollment:
                self.fields["classroom"].initial = enrollment.classroom_id
            if self.instance.user_id:
                del self.fields["create_login"]
        # Show the class right after the name.
        order = ["admission_number", "first_name", "last_name", "classroom"]
        self.order_fields(order + [name for name in self.fields if name not in order])

    def save(self, commit=True):
        student = super().save(commit=commit)
        classroom = self.cleaned_data.get("classroom")
        if commit and classroom is not None:
            enrollment, created = Enrollment.objects.get_or_create(
                student=student, academic_year=self.year, defaults={"classroom": classroom}
            )
            if not created and (enrollment.classroom_id != classroom.pk or enrollment.status != Enrollment.Status.ACTIVE):
                enrollment.classroom = classroom
                enrollment.status = Enrollment.Status.ACTIVE
                enrollment.save(update_fields=["classroom", "status"])
        return student


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


class TeacherForm(forms.Form):
    """One form for a teacher's login, salary record and class/subject assignments."""

    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    phone = forms.CharField(max_length=30, required=False, help_text="Used for the username and to send the password on WhatsApp.")
    username = forms.CharField(
        max_length=150,
        required=False,
        help_text="Leave empty to use the phone number.",
    )
    monthly_salary = forms.DecimalField(
        label="Monthly salary (Rs)", max_digits=10, decimal_places=2, min_value=0, required=False
    )
    class_teacher_of = forms.ModelChoiceField(
        queryset=Classroom.objects.none(),
        required=False,
        label="Class teacher of",
        help_text="The class teacher can edit that class's timetable.",
    )

    def __init__(self, *args, teacher=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.teacher = teacher
        self.year = AcademicYear.objects.filter(is_active=True).first()
        self.classrooms = list(Classroom.objects.filter(academic_year=self.year).order_by("name", "section"))
        self.subjects = list(Subject.objects.order_by("name"))
        self.fields["class_teacher_of"].queryset = Classroom.objects.filter(academic_year=self.year).order_by(
            "name", "section"
        )
        valid = {f"{c.pk}-{s.pk}" for c in self.classrooms for s in self.subjects}
        self.selected = {value for value in (self.data.getlist("assign") if self.is_bound else []) if value in valid}
        if not self.is_bound and teacher is not None:
            self.selected = {
                f"{a.classroom_id}-{a.subject_id}"
                for a in teacher.assignments.filter(classroom__academic_year=self.year)
            }

    def assignment_rows(self):
        """Rows of (classroom, [(value, subject, checked)]) for the checkbox grid."""
        return [
            (
                classroom,
                [(f"{classroom.pk}-{s.pk}", s, f"{classroom.pk}-{s.pk}" in self.selected) for s in self.subjects],
            )
            for classroom in self.classrooms
        ]

    def clean_username(self):
        username = self.cleaned_data["username"].strip().lower()
        if username:
            taken = get_user_model().objects.filter(username=username)
            if self.teacher is not None:
                taken = taken.exclude(pk=self.teacher.user_id)
            if taken.exists():
                raise forms.ValidationError("This username is already used by someone else.")
        return username


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ("name", "code")
        help_texts = {"code": "A short unique code, e.g. MATH."}
