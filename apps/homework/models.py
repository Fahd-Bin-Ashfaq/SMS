from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.academics.models import Classroom, Subject, TeacherAssignment


class Homework(models.Model):
    classroom = models.ForeignKey(
        Classroom, on_delete=models.PROTECT, related_name="homework"
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.PROTECT, related_name="homework"
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="homework_assignments",
    )
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    assigned_date = models.DateField()
    due_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-assigned_date", "classroom__name", "subject__name", "title")
        constraints = [
            models.CheckConstraint(
                condition=Q(due_date__gte=F("assigned_date")),
                name="homework_due_on_or_after_assigned",
            )
        ]

    def __str__(self):
        return f"{self.title} — {self.classroom} / {self.subject}"

    def clean(self):
        super().clean()
        errors = {}
        if self.assigned_date and self.due_date and self.due_date < self.assigned_date:
            errors["due_date"] = "Due date must be on or after the assigned date."

        if self.assigned_by_id and self.classroom_id and self.subject_id:
            if getattr(self.assigned_by, "role", None) != "teacher":
                errors["assigned_by"] = "Homework must be assigned by a teacher."
            elif not TeacherAssignment.objects.filter(
                teacher__user_id=self.assigned_by_id,
                classroom_id=self.classroom_id,
                subject_id=self.subject_id,
            ).exists():
                errors["subject"] = (
                    "You must be assigned to this classroom and subject to assign homework."
                )
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
