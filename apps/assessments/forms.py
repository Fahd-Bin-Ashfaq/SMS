from decimal import Decimal

from django import forms

from apps.academics.models import Enrollment, TeacherAssignment
from apps.assessments.models import (
    Exam,
    ExamSubject,
    StudentMark,
    active_enrollments,
)
from apps.assessments.permissions import user_role


class MarkEntryForm(forms.Form):
    exam = forms.ModelChoiceField(queryset=Exam.objects.none())
    exam_subject = forms.ModelChoiceField(
        queryset=ExamSubject.objects.none(), label="Subject"
    )
    enrollment = forms.ModelChoiceField(queryset=Enrollment.objects.none())
    marks_awarded = forms.DecimalField(
        max_digits=7,
        decimal_places=2,
        min_value=Decimal("0"),
        error_messages={"min_value": "Marks awarded cannot be negative."},
        label="Marks awarded",
        widget=forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
    )

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.assignments = TeacherAssignment.objects.filter(teacher__user=user)
        exam_subjects = ExamSubject.objects.select_related(
            "exam", "exam__classroom", "subject"
        ).filter(
            exam__classroom__in=self.assignments.values("classroom_id"),
            subject__in=self.assignments.values("subject_id"),
        )
        self.fields["exam_subject"].queryset = exam_subjects
        self.fields["exam"].queryset = Exam.objects.filter(
            pk__in=exam_subjects.values("exam_id")
        )
        self.fields["enrollment"].queryset = active_enrollments().filter(
            classroom__in=self.assignments.values("classroom_id"),
            academic_year__in=Exam.objects.filter(
                classroom__in=self.assignments.values("classroom_id")
            ).values("academic_year_id"),
        ).select_related("student", "classroom")
        self.fields["enrollment"].label_from_instance = lambda enrollment: (
            f"{enrollment.student} — {enrollment.classroom}"
        )

    def clean(self):
        cleaned = super().clean()
        exam = cleaned.get("exam")
        exam_subject = cleaned.get("exam_subject")
        enrollment = cleaned.get("enrollment")
        marks = cleaned.get("marks_awarded")

        if exam and exam_subject:
            if exam_subject.exam_id != exam.pk:
                self.add_error("exam_subject", "Select a subject belonging to the selected exam.")
            elif not self.assignments.filter(
                classroom_id=exam.classroom_id, subject_id=exam_subject.subject_id
            ).exists():
                self.add_error(
                    "exam_subject", "You are not assigned to this class and subject."
                )
        if exam and enrollment and (
            enrollment.classroom_id != exam.classroom_id
            or enrollment.academic_year_id != exam.academic_year_id
        ):
            self.add_error(
                "enrollment", "Select a student enrolled in the exam's class and year."
            )
        if exam_subject and marks is not None and marks > exam_subject.maximum_marks:
            self.add_error(
                "marks_awarded",
                f"Marks awarded cannot exceed the maximum of {exam_subject.maximum_marks}.",
            )
        return cleaned

    def save(self):
        exam = self.cleaned_data["exam"]
        exam_subject = self.cleaned_data["exam_subject"]
        enrollment = self.cleaned_data["enrollment"]
        mark, _ = StudentMark.objects.update_or_create(
            exam=exam,
            student=enrollment.student,
            subject=exam_subject.subject,
            defaults={
                "marks_awarded": self.cleaned_data["marks_awarded"],
                "updated_by": self.user,
            },
        )
        return mark
