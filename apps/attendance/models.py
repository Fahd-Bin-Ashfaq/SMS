from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


class AttendanceRecord(models.Model):
    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        ABSENT = "absent", "Absent"
        LATE = "late", "Late"

    enrollment = models.ForeignKey(
        "academics.Enrollment",
        on_delete=models.PROTECT,
        related_name="attendance_records",
    )
    date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="attendance_records",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-date", "enrollment__student__last_name")
        constraints = [
            models.UniqueConstraint(
                fields=("enrollment", "date"),
                name="attendance_unique_enrollment_date",
            )
        ]
        indexes = [models.Index(fields=("date", "status"))]

    def __str__(self):
        return f"{self.enrollment} — {self.date}: {self.get_status_display()}"

    def clean(self):
        super().clean()
        if not self.enrollment_id or not self.date:
            return

        enrollment = self.enrollment
        is_active = enrollment.status == "active"
        stored_enrollment_id = None
        if self.pk:
            stored_enrollment_id = (
                type(self).objects.filter(pk=self.pk)
                .values_list("enrollment_id", flat=True)
                .first()
            )
        if not is_active and (
            self._state.adding or stored_enrollment_id != self.enrollment_id
        ):
            raise ValidationError({"enrollment": "Attendance can only be recorded for an active enrollment."})

        academic_year = enrollment.academic_year
        if not academic_year.start_date <= self.date <= academic_year.end_date:
            raise ValidationError({"date": "The date must fall within the enrollment's academic year."})
        if self.date > timezone.localdate():
            raise ValidationError({"date": "Attendance cannot be recorded for a future date."})

    def save(self, *args, **kwargs):
        self.full_clean()
        with transaction.atomic():
            previous_status = None
            if self.pk:
                previous_status = (
                    type(self).objects.select_for_update()
                    .filter(pk=self.pk)
                    .values_list("status", flat=True)
                    .first()
                )
            super().save(*args, **kwargs)
            if previous_status and previous_status != self.status:
                AttendanceCorrection.objects.create(
                    attendance=self,
                    changed_by=getattr(self, "_changed_by", None),
                    previous_status=previous_status,
                    new_status=self.status,
                    reason=getattr(self, "_correction_reason", ""),
                )


class AttendanceCorrection(models.Model):
    attendance = models.ForeignKey(
        AttendanceRecord,
        on_delete=models.CASCADE,
        related_name="corrections",
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_corrections",
    )
    previous_status = models.CharField(max_length=10, choices=AttendanceRecord.Status.choices)
    new_status = models.CharField(max_length=10, choices=AttendanceRecord.Status.choices)
    reason = models.CharField(max_length=500, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-changed_at",)

    def __str__(self):
        return f"{self.attendance}: {self.previous_status} → {self.new_status}"
