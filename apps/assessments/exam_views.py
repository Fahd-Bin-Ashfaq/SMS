"""Exam setup, date sheets, class-wide mark entry and result cards."""

from datetime import date, time
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.academics.models import Classroom, TeacherAssignment

from .forms import ExamCreateForm
from .models import Exam, ExamSubject, ResultRemark, StudentMark, active_enrollments
from .permissions import can_access_exam, user_role
from .results import class_results


def _require_principal(user):
    if user_role(user) != "principal":
        raise PermissionDenied("Only the principal can do this.")


def _is_class_teacher(user, exam):
    teacher = exam.classroom.class_teacher
    return teacher is not None and teacher.user_id == user.pk


def _class_students(exam):
    return [
        enrollment.student
        for enrollment in active_enrollments()
        .filter(classroom=exam.classroom, academic_year=exam.academic_year)
        .select_related("student")
        .order_by("student__first_name", "student__last_name")
    ]


@login_required
@require_http_methods(["GET", "POST"])
def exam_create(request):
    """Create one exam (e.g. Mid-term) for several classes at once."""
    _require_principal(request.user)
    classrooms = Classroom.objects.filter(academic_year__is_active=True).order_by("name", "section")
    form = ExamCreateForm(request.POST or None, classrooms=classrooms)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        created = 0
        with transaction.atomic():
            for classroom in data["classrooms"]:
                exam, was_created = Exam.objects.get_or_create(
                    academic_year=classroom.academic_year,
                    classroom=classroom,
                    name=data["name"],
                    defaults={"date": data["date"]},
                )
                created += was_created
                subject_ids = set(
                    TeacherAssignment.objects.filter(classroom=classroom).values_list("subject_id", flat=True)
                )
                for subject_id in subject_ids:
                    ExamSubject.objects.get_or_create(
                        exam=exam, subject_id=subject_id, defaults={"maximum_marks": data["maximum_marks"]}
                    )
        plural = "es" if created != 1 else ""
        messages.success(request, f"{data['name']} created for {created} class{plural}. Now set the date sheet.")
        return redirect("assessments:index")
    return render(request, "assessments/exam_create.html", {"form": form})


def _parse_paper(post, exam_subject):
    prefix = f"s{exam_subject.pk}_"
    paper_date = post.get(prefix + "date")
    start, end = post.get(prefix + "start"), post.get(prefix + "end")
    exam_subject.paper_date = date.fromisoformat(paper_date) if paper_date else None
    exam_subject.start_time = time.fromisoformat(start) if start else None
    exam_subject.end_time = time.fromisoformat(end) if end else None
    exam_subject.maximum_marks = Decimal(post.get(prefix + "max") or "0")
    exam_subject.full_clean()


@login_required
@require_http_methods(["GET", "POST"])
def date_sheet(request, exam_id):
    exam = get_object_or_404(Exam.objects.select_related("classroom", "academic_year"), pk=exam_id)
    if not can_access_exam(request.user, exam):
        raise PermissionDenied
    can_edit = user_role(request.user) == "principal"
    exam_subjects = list(exam.subjects.select_related("subject"))
    errors = []
    if request.method == "POST":
        if not can_edit:
            raise PermissionDenied
        for exam_subject in exam_subjects:
            try:
                _parse_paper(request.POST, exam_subject)
            except (ValueError, InvalidOperation, ValidationError):
                errors.append(f"Check the date, time and maximum marks for {exam_subject.subject.name}.")
        if not errors:
            copied = 0
            with transaction.atomic():
                for exam_subject in exam_subjects:
                    exam_subject.save()
                if request.POST.get("copy"):
                    others = Exam.objects.filter(academic_year=exam.academic_year, name=exam.name).exclude(pk=exam.pk)
                    for exam_subject in exam_subjects:
                        copied += ExamSubject.objects.filter(exam__in=others, subject=exam_subject.subject).update(
                            paper_date=exam_subject.paper_date,
                            start_time=exam_subject.start_time,
                            end_time=exam_subject.end_time,
                        )
            note = " The same dates were copied to the other classes." if copied else ""
            messages.success(request, f"Date sheet saved.{note}")
            return redirect("assessments:date-sheet", exam_id=exam.pk)
    return render(
        request,
        "assessments/date_sheet.html",
        {"exam": exam, "exam_subjects": exam_subjects, "can_edit": can_edit, "errors": errors},
    )


@login_required
@require_http_methods(["GET", "POST"])
def class_marks(request, exam_id, subject_id):
    """Enter one subject's marks for the whole class on one page."""
    exam = get_object_or_404(Exam.objects.select_related("classroom", "academic_year"), pk=exam_id)
    exam_subject = get_object_or_404(ExamSubject.objects.select_related("subject"), exam=exam, subject_id=subject_id)
    role = user_role(request.user)
    teaches = TeacherAssignment.objects.filter(
        teacher__user=request.user, classroom=exam.classroom, subject_id=subject_id
    ).exists()
    if not (role == "principal" or (role == "teacher" and teaches)):
        raise PermissionDenied("Only the subject's teacher can enter these marks.")
    students = _class_students(exam)
    existing = {m.student_id: m for m in StudentMark.objects.filter(exam=exam, subject_id=subject_id)}
    errors = {}
    if request.method == "POST":
        values = {}
        for student in students:
            raw = request.POST.get(f"marks_{student.pk}", "").strip()
            if raw == "":
                continue
            try:
                value = Decimal(raw)
                if value < 0 or value > exam_subject.maximum_marks:
                    raise InvalidOperation
                values[student.pk] = value
            except InvalidOperation:
                errors[student.pk] = f"Enter a number from 0 to {exam_subject.maximum_marks:g}."
        if not errors:
            with transaction.atomic():
                for student in students:
                    if student.pk not in values:
                        continue
                    mark = existing.get(student.pk) or StudentMark(exam=exam, student=student, subject_id=subject_id)
                    if mark.pk and mark.marks_awarded == values[student.pk]:
                        continue
                    mark.marks_awarded = values[student.pk]
                    mark.updated_by = request.user
                    mark.save()
            messages.success(request, f"{exam_subject.subject.name} marks saved for {len(values)} students.")
            return redirect("assessments:index")
    for student in students:
        if request.method == "POST":
            student.entered = request.POST.get(f"marks_{student.pk}", "")
        else:
            student.entered = f"{existing[student.pk].marks_awarded:g}" if student.pk in existing else ""
        student.error = errors.get(student.pk)
    return render(
        request,
        "assessments/class_marks.html",
        {"exam": exam, "exam_subject": exam_subject, "students": students},
    )


@login_required
@require_http_methods(["GET", "POST"])
def result_cards(request, exam_id):
    exam = get_object_or_404(
        Exam.objects.select_related("classroom__class_teacher__user", "academic_year"), pk=exam_id
    )
    if not can_access_exam(request.user, exam):
        raise PermissionDenied
    is_principal = user_role(request.user) == "principal"
    can_remark = is_principal or _is_class_teacher(request.user, exam)
    if request.method == "POST":
        if request.POST.get("action") == "publish":
            if not is_principal:
                raise PermissionDenied
            exam.results_published = request.POST.get("publish") == "1"
            exam.save(update_fields=["results_published"])
            if exam.results_published:
                messages.success(request, "Results are now visible to students and parents.")
            else:
                messages.success(request, "Results are hidden from students and parents.")
        else:
            if not can_remark:
                raise PermissionDenied
            enrolled = {student.pk for student in _class_students(exam)}
            for key, value in request.POST.items():
                number = key.removeprefix("remark_")
                if number == key or not number.isdigit() or int(number) not in enrolled:
                    continue
                text = value.strip()[:300]
                if text:
                    ResultRemark.objects.update_or_create(
                        exam=exam, student_id=int(number), defaults={"remarks": text, "updated_by": request.user}
                    )
                else:
                    ResultRemark.objects.filter(exam=exam, student_id=int(number)).delete()
            messages.success(request, "Remarks saved.")
        return redirect("assessments:result-cards", exam_id=exam.pk)
    return render(
        request,
        "assessments/result_cards.html",
        {"exam": exam, "result": class_results(exam), "can_remark": can_remark, "is_principal": is_principal},
    )
