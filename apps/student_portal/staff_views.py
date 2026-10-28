"""Pages staff use to talk to students and parents."""

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.academics.models import Classroom

from .models import Notification

NOTICE_ROLES = {"principal", "office", "teacher"}


def _classes_for(user):
    classes = Classroom.objects.filter(academic_year__is_active=True).order_by("name", "section")
    if user.role == "teacher":
        classes = classes.filter(teacher_assignments__teacher__user=user).distinct()
    return classes


class NoticeForm(forms.ModelForm):
    class Meta:
        model = Notification
        fields = ("title", "message", "classroom")
        widgets = {"message": forms.Textarea(attrs={"rows": 4})}
        labels = {"classroom": "Send to"}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["classroom"].queryset = _classes_for(user)
        if user.role == "teacher":
            self.fields["classroom"].required = True
            self.fields["classroom"].empty_label = None
            self.fields["classroom"].help_text = "Teachers can send notices to the classes they teach."
        else:
            self.fields["classroom"].empty_label = "Whole school"
            self.fields["classroom"].help_text = "Choose a class, or leave as Whole school."


@login_required
def notices(request):
    if getattr(request.user, "role", None) not in NOTICE_ROLES:
        raise PermissionDenied
    form = NoticeForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        notice = form.save(commit=False)
        notice.created_by = request.user
        notice.save()
        target = f"{notice.classroom.name} {notice.classroom.section}" if notice.classroom else "the whole school"
        messages.success(request, f'Notice "{notice.title}" sent to {target}.')
        return redirect("student_portal:notices")
    listing = Notification.objects.select_related("classroom", "created_by").order_by("-created_at")
    if request.user.role == "teacher":
        listing = listing.filter(created_by=request.user)
    return render(request, "student_portal/staff_notices.html", {"form": form, "notices": listing[:50]})


@login_required
@require_POST
def notice_delete(request, pk):
    notice = get_object_or_404(Notification, pk=pk)
    if not (request.user.role == "principal" or notice.created_by_id == request.user.pk):
        raise PermissionDenied
    notice.delete()
    messages.success(request, "Notice removed.")
    return redirect("student_portal:notices")
