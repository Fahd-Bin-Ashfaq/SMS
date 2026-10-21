from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        PRINCIPAL = "principal", "Principal"
        TEACHER = "teacher", "Teacher"
        STUDENT = "student", "Student"
        OFFICE = "office", "Office staff"

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.TEACHER,
    )

    def __str__(self):
        return self.get_full_name() or self.username
