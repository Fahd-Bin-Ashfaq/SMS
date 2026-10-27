import calendar
from datetime import date

from django import forms
from django.forms import BaseFormSet, formset_factory
from django.utils import timezone

from apps.academics.models import Classroom, Enrollment, Subject
from .models import AttendanceRecord


class AttendanceFilterForm(forms.Form):
    classroom = forms.ModelChoiceField(queryset=Classroom.objects.none(), label="Class")
    subject = forms.ModelChoiceField(queryset=Subject.objects.none(), required=False)
    date = forms.DateField(
        initial=timezone.localdate,
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def __init__(self, *args, classrooms=None, subjects=None, require_subject=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["classroom"].queryset = classrooms if classrooms is not None else Classroom.objects.none()
        self.fields["subject"].queryset = subjects if subjects is not None else Subject.objects.none()
        self.fields["subject"].required = require_subject

    def clean(self):
        cleaned_data = super().clean()
        classroom = cleaned_data.get("classroom")
        attendance_date = cleaned_data.get("date")
        if classroom and attendance_date:
            academic_year = classroom.academic_year
            if not academic_year.start_date <= attendance_date <= academic_year.end_date:
                self.add_error("date", "Choose a date within this class's academic year.")
            elif attendance_date > timezone.localdate():
                self.add_error("date", "Attendance cannot be recorded for a future date.")
        return cleaned_data


class AttendanceRowForm(forms.Form):
    enrollment = forms.ModelChoiceField(
        queryset=Enrollment.objects.none(),
        widget=forms.HiddenInput,
    )
    status = forms.ChoiceField(choices=AttendanceRecord.Status.choices, widget=forms.RadioSelect)

    def __init__(self, *args, enrollments=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["enrollment"].queryset = (
            enrollments if enrollments is not None else Enrollment.objects.none()
        )


class AttendanceRowFormSetBase(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        enrollment_ids = [
            form.cleaned_data["enrollment"].pk
            for form in self.forms
            if form.cleaned_data.get("enrollment")
        ]
        if len(enrollment_ids) != len(set(enrollment_ids)):
            raise forms.ValidationError("An enrollment may only appear once in the roster.")


AttendanceRowFormSet = formset_factory(
    AttendanceRowForm,
    formset=AttendanceRowFormSetBase,
    extra=0,
)


class MonthFilterForm(forms.Form):
    classroom = forms.ModelChoiceField(queryset=Classroom.objects.none(), label="Class")
    subject = forms.ModelChoiceField(queryset=Subject.objects.none(), required=False)
    month = forms.CharField(
        widget=forms.DateInput(attrs={"type": "month"}),
        initial=lambda: timezone.localdate().strftime("%Y-%m"),
    )

    def __init__(self, *args, classrooms=None, subjects=None, require_subject=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["classroom"].queryset = classrooms if classrooms is not None else Classroom.objects.none()
        self.fields["subject"].queryset = subjects if subjects is not None else Subject.objects.none()
        self.fields["subject"].required = require_subject

    def clean_month(self):
        value = self.cleaned_data["month"]
        try:
            year_text, month_text = value.split("-", 1)
            year, month = int(year_text), int(month_text)
            last_day = calendar.monthrange(year, month)[1]
            return date(year, month, 1), date(year, month, last_day)
        except (ValueError, TypeError):
            raise forms.ValidationError("Enter a valid month.")
