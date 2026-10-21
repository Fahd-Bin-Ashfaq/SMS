from decimal import Decimal

from django.conf import settings
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import models, transaction
from django.db.models import F, Q

from apps.academics.models import AcademicYear, Classroom, Enrollment, Student, Subject


def active_enrollments():
    queryset = Enrollment.objects.all()
    for flag in ("is_active", "active"):
        try:
            Enrollment._meta.get_field(flag)
        except FieldDoesNotExist:
            continue
        return queryset.filter(**{flag: True})
    try:
        status_field = Enrollment._meta.get_field("status")
    except FieldDoesNotExist:
        return queryset
    if any(value == "active" for value, _label in status_field.choices):
        return queryset.filter(status="active")
    return queryset


class Exam(models.Model):
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.PROTECT, related_name="exams"
    )
    classroom = models.ForeignKey(
        Classroom, on_delete=models.PROTECT, related_name="exams"
    )
    name = models.CharField(max_length=120)
    date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ("-date", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("academic_year", "classroom", "name"),
                name="assess_exam_year_class_name_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.name} — {self.classroom} ({self.academic_year})"

    def clean(self):
        super().clean()
        if (
            self.classroom_id
            and self.academic_year_id
            and hasattr(self.classroom, "academic_year_id")
            and self.classroom.academic_year_id != self.academic_year_id
        ):
            raise ValidationError(
                {"classroom": "The classroom must belong to the selected academic year."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ExamSubject(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="subjects")
    subject = models.ForeignKey(
        Subject, on_delete=models.PROTECT, related_name="exam_subjects"
    )
    maximum_marks = models.DecimalField(max_digits=7, decimal_places=2)

    class Meta:
        ordering = ("subject__name",)
        constraints = [
            models.UniqueConstraint(
                fields=("exam", "subject"), name="assess_exam_subject_uniq"
            ),
            models.CheckConstraint(
                condition=Q(maximum_marks__gt=0),
                name="assess_exam_subject_max_positive",
            ),
        ]

    def __str__(self):
        return f"{self.exam}: {self.subject} (out of {self.maximum_marks})"

    def clean(self):
        super().clean()
        if self.maximum_marks is not None and self.maximum_marks <= Decimal("0"):
            raise ValidationError({"maximum_marks": "Maximum marks must be greater than zero."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class StudentMark(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="marks")
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="marks")
    subject = models.ForeignKey(
        Subject, on_delete=models.PROTECT, related_name="student_marks"
    )
    marks_awarded = models.DecimalField(max_digits=7, decimal_places=2)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assessment_mark_updates",
    )

    class Meta:
        ordering = ("student__last_name", "student__first_name", "subject__name")
        constraints = [
            models.UniqueConstraint(
                fields=("exam", "student", "subject"), name="assess_exam_student_subject_uniq"
            ),
            models.CheckConstraint(
                condition=Q(marks_awarded__gte=0), name="assess_mark_nonnegative"
            ),
        ]

    def __str__(self):
        return f"{self.student}: {self.marks_awarded} — {self.exam} / {self.subject}"

    def clean(self):
        super().clean()
        errors = {}
        if self.marks_awarded is not None and self.marks_awarded < Decimal("0"):
            errors["marks_awarded"] = "Marks awarded cannot be negative."

        if self.exam_id and self.subject_id:
            exam_subject = ExamSubject.objects.filter(
                exam_id=self.exam_id, subject_id=self.subject_id
            ).first()
            if exam_subject is None:
                errors["subject"] = "This subject is not included in the selected exam."
            elif (
                self.marks_awarded is not None
                and self.marks_awarded > exam_subject.maximum_marks
            ):
                errors["marks_awarded"] = (
                    f"Marks awarded cannot exceed the maximum of "
                    f"{exam_subject.maximum_marks}."
                )

        if self.exam_id and self.student_id:
            enrolled = active_enrollments().filter(
                student_id=self.student_id,
                classroom_id=self.exam.classroom_id,
                academic_year_id=self.exam.academic_year_id,
            ).exists()
            if not enrolled:
                errors["student"] = (
                    "The student must be enrolled in the exam's classroom and academic year."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        previous_marks = None
        if self.pk:
            previous_marks = (
                type(self).objects.filter(pk=self.pk)
                .values_list("marks_awarded", flat=True)
                .first()
            )
        self.full_clean()
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            if previous_marks != self.marks_awarded:
                MarkChange.objects.create(
                    mark=self,
                    previous_marks=previous_marks,
                    new_marks=self.marks_awarded,
                    changed_by=self.updated_by,
                )
        return result


class MarkChange(models.Model):
    mark = models.ForeignKey(
        StudentMark, on_delete=models.CASCADE, related_name="changes"
    )
    previous_marks = models.DecimalField(
        max_digits=7, decimal_places=2, null=True, blank=True
    )
    new_marks = models.DecimalField(max_digits=7, decimal_places=2)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assessment_mark_changes",
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-changed_at",)


# Publicly useful alias for the domain term used in the project README.
Mark = StudentMark
