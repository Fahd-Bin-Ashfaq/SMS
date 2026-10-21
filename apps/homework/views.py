from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.homework.forms import HomeworkForm
from apps.homework.models import Homework


def _role(user):
    return getattr(user, "role", "")


def _is_reviewer(user):
    return _role(user) in {"principal", "office"} or user.is_superuser


def _teacher_homework(user):
    return Homework.objects.filter(
        classroom__teacher_assignments__teacher__user=user,
        classroom__teacher_assignments__subject_id=F("subject_id"),
    ).distinct()


@login_required
def index(request):
    if _is_reviewer(request.user):
        homework = Homework.objects.all()
        template = "homework/review.html"
    elif _role(request.user) == "teacher":
        homework = _teacher_homework(request.user)
        template = "homework/index.html"
    else:
        raise PermissionDenied("You do not have access to homework.")
    homework = homework.select_related("classroom", "subject", "assigned_by")
    return render(request, template, {"homework_list": homework})


@login_required
@require_http_methods(["GET", "POST"])
def create(request):
    if _role(request.user) != "teacher":
        raise PermissionDenied("Only teachers can assign homework.")
    data = request.POST if request.method == "POST" else None
    form = HomeworkForm(data, user=request.user)
    if request.method == "POST":
        if form.is_valid():
            homework = form.save()
            messages.success(request, f'Homework "{homework.title}" was assigned.')
            return redirect("homework:index")
        messages.error(request, "Homework was not assigned. Correct the errors below.")
    return render(request, "homework/form.html", {"form": form, "heading": "Assign homework"})


@login_required
@require_http_methods(["GET", "POST"])
def edit(request, homework_id):
    if _role(request.user) != "teacher":
        raise PermissionDenied("Only the assigning teacher can edit homework.")
    homework = get_object_or_404(
        Homework.objects.filter(assigned_by=request.user), pk=homework_id
    )
    if not _teacher_homework(request.user).filter(pk=homework.pk).exists():
        raise PermissionDenied("You are no longer assigned to this classroom and subject.")
    form = HomeworkForm(
        request.POST if request.method == "POST" else None,
        instance=homework,
        user=request.user,
    )
    if request.method == "POST":
        if form.is_valid():
            homework = form.save()
            messages.success(request, f'Homework "{homework.title}" was updated.')
            return redirect("homework:index")
        messages.error(request, "Homework was not updated. Correct the errors below.")
    return render(
        request,
        "homework/form.html",
        {"form": form, "heading": "Edit homework", "homework": homework},
    )


@login_required
def review(request):
    if not _is_reviewer(request.user):
        raise PermissionDenied("Only principal or office staff can review all homework.")
    homework = Homework.objects.select_related(
        "classroom", "subject", "assigned_by"
    )
    return render(request, "homework/review.html", {"homework_list": homework})
