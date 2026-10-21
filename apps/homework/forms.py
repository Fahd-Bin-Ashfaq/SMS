from django import forms
from django.utils import timezone

from apps.academics.models import Classroom, Subject, TeacherAssignment
from apps.homework.models import Homework


class HomeworkForm(forms.ModelForm):
    class Meta:
        model = Homework
        fields = (
            "title",
            "description",
            "classroom",
            "subject",
            "assigned_date",
            "due_date",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "assigned_date": forms.DateInput(attrs={"type": "date"}),
            "due_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.assignments = TeacherAssignment.objects.filter(
            teacher__user=user
        ).select_related("classroom", "subject")
        self.fields["classroom"].queryset = Classroom.objects.filter(
            pk__in=self.assignments.values("classroom_id")
        )
        self.fields["subject"].queryset = Subject.objects.filter(
            pk__in=self.assignments.values("subject_id")
        )
        self.fields["assigned_date"].initial = timezone.localdate

    def clean(self):
        cleaned = super().clean()
        classroom = cleaned.get("classroom")
        subject = cleaned.get("subject")
        if classroom and subject and not self.assignments.filter(
            classroom_id=classroom.pk, subject_id=subject.pk
        ).exists():
            self.add_error(
                "subject",
                "You are not assigned to this classroom and subject.",
            )
        assigned_date = cleaned.get("assigned_date")
        due_date = cleaned.get("due_date")
        if assigned_date and due_date and due_date < assigned_date:
            self.add_error(
                "due_date", "Due date must be on or after the assigned date."
            )
        return cleaned

    def save(self, commit=True):
        homework = super().save(commit=False)
        homework.assigned_by = self.user
        if commit:
            homework.save()
        return homework
