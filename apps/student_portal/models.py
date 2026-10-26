from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class StudyGuide(models.Model):
    classroom = models.ForeignKey(
        "academics.Classroom", on_delete=models.CASCADE, related_name="study_guides"
    )
    subject = models.ForeignKey(
        "academics.Subject",
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="study_guides",
    )
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    file = models.FileField(upload_to="study_guides/", blank=True)
    link = models.URLField(blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="study_guides",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at", "title")

    def __str__(self):
        return f"{self.title} — {self.classroom}"

    def clean(self):
        super().clean()
        if not self.file and not self.link and not self.description:
            raise ValidationError("Add a file, a link or a description.")


class Notification(models.Model):
    title = models.CharField(max_length=160)
    message = models.TextField()
    classroom = models.ForeignKey(
        "academics.Classroom",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="notifications",
        help_text="Leave blank to send to every student.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="student_notifications",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.title
