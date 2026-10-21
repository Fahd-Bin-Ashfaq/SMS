from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.academics.models import TeacherAssignment
from apps.assessments.forms import MarkEntryForm
from apps.assessments.models import Exam, StudentMark
from apps.assessments.permissions import can_access_exam, is_reviewer, user_role


def _require_reviewer(user):
    if not is_reviewer(user):
        raise PermissionDenied("Only principal or office staff can review assessments.")


@login_required
def index(request):
    role = user_role(request.user)
    if is_reviewer(request.user):
        exams = Exam.objects.select_related("academic_year", "classroom")
    elif role == "teacher":
        exams = Exam.objects.filter(
            classroom__teacherassignment__teacher__user=request.user
        ).distinct().select_related("academic_year", "classroom")
    else:
        raise PermissionDenied("You do not have access to assessments.")
    return render(request, "assessments/index.html", {"exams": exams})


@login_required
@require_http_methods(["GET", "POST"])
def enter_marks(request):
    if user_role(request.user) != "teacher":
        raise PermissionDenied("Only teachers can enter marks.")
    form = MarkEntryForm(
        request.POST or None,
        user=request.user,
    )
    if request.method == "POST":
        if form.is_valid():
            mark = form.save()
            messages.success(
                request,
                f"Marks saved for {mark.student} in {mark.subject}: {mark.marks_awarded}.",
            )
            return redirect("assessments:mark-entry")
        messages.error(request, "Marks were not saved. Correct the errors below.")
    return render(request, "assessments/mark_entry.html", {"form": form})


@login_required
def review(request):
    _require_reviewer(request.user)
    marks = StudentMark.objects.select_related(
        "exam", "exam__classroom", "exam__academic_year", "student", "subject"
    )
    return render(request, "assessments/review.html", {"marks": marks})


@login_required
def result_sheet(request, exam_id):
    exam = get_object_or_404(
        Exam.objects.select_related("classroom", "academic_year"), pk=exam_id
    )
    if not can_access_exam(request.user, exam):
        raise PermissionDenied("You are not assigned to this class or cannot review results.")

    marks = StudentMark.objects.filter(exam=exam).select_related(
        "student", "subject"
    )
    subjects = exam.subjects.select_related("subject")
    if user_role(request.user) == "teacher":
        assigned_subject_ids = TeacherAssignment.objects.filter(
            teacher__user=request.user, classroom=exam.classroom
        ).values("subject_id")
        marks = marks.filter(
            subject_id__in=assigned_subject_ids,
        ).distinct()
        subjects = subjects.filter(subject_id__in=assigned_subject_ids)

    rows = {}
    for mark in marks:
        row = rows.setdefault(
            mark.student_id,
            {"student": mark.student, "marks": {}, "total": 0},
        )
        row["marks"][mark.subject_id] = mark.marks_awarded
        row["total"] += mark.marks_awarded
    return render(
        request,
        "assessments/result_sheet.html",
        {"exam": exam, "subjects": subjects, "rows": rows.values()},
    )
