from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class AcademicYear(models.Model):
    name = models.CharField(max_length=50, unique=True)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ("-start_date", "name")
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=models.F("start_date")),
                name="academics_year_end_on_or_after_start",
            ),
            models.UniqueConstraint(
                fields=("is_active",),
                condition=Q(is_active=True),
                name="academics_only_one_active_year",
            ),
        ]

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError({"end_date": "End date must be on or after start date."})

    def __str__(self):
        return self.name


class Student(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="student_profile",
    )
    admission_number = models.CharField(max_length=50, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(blank=True, null=True)
    guardian_name = models.CharField(max_length=200, blank=True)
    guardian_phone = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("last_name", "first_name", "admission_number")

    def __str__(self):
        return f"{self.admission_number} — {self.first_name} {self.last_name}"


class Teacher(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="teacher_profile",
    )

    def __str__(self):
        return self.user.get_full_name() or self.user.get_username()


class Classroom(models.Model):
    name = models.CharField(max_length=100)
    section = models.CharField(max_length=50)
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.PROTECT, related_name="classrooms"
    )

    class Meta:
        ordering = ("academic_year__start_date", "name", "section")
        constraints = [
            models.UniqueConstraint(
                fields=("name", "section", "academic_year"),
                name="academics_unique_classroom_per_year",
            )
        ]

    def __str__(self):
        return f"{self.name} {self.section} ({self.academic_year})"


class Enrollment(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="enrollments")
    classroom = models.ForeignKey(
        Classroom, on_delete=models.PROTECT, related_name="enrollments"
    )
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.PROTECT, related_name="enrollments"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        ordering = ("academic_year__start_date", "classroom__name", "student__last_name")
        constraints = [
            models.UniqueConstraint(
                fields=("student", "academic_year"),
                name="academics_unique_student_enrollment_per_year",
            ),
            models.CheckConstraint(
                condition=Q(status__in=("active", "inactive")),
                name="academics_enrollment_status_valid",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.classroom_id
            and self.academic_year_id
            and self.classroom.academic_year_id != self.academic_year_id
        ):
            raise ValidationError(
                {"academic_year": "Enrollment year must match the classroom's academic year."}
            )

    def __str__(self):
        return f"{self.student} — {self.classroom} [{self.get_status_display()}]"


class Subject(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=30, unique=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return f"{self.name} ({self.code})"


class TeacherAssignment(models.Model):
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, related_name="assignments")
    classroom = models.ForeignKey(
        Classroom, on_delete=models.CASCADE, related_name="teacher_assignments"
    )
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name="assignments")

    class Meta:
        ordering = ("classroom__name", "subject__name", "teacher__user__last_name")
        constraints = [
            models.UniqueConstraint(
                fields=("teacher", "classroom", "subject"),
                name="academics_unique_teacher_class_subject",
            )
        ]

    def __str__(self):
        return f"{self.teacher} — {self.subject} — {self.classroom}"
