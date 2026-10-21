from datetime import date
from decimal import Decimal

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import FieldError, PermissionDenied
from django.db.models import Avg, Count, Sum
from django.shortcuts import render
from django.utils import timezone


ROLE_PRINCIPAL = "principal"
ROLE_TEACHER = "teacher"
ROLE_STUDENT = "student"
ROLE_OFFICE = "office"
ALLOWED_ROLES = {ROLE_PRINCIPAL, ROLE_TEACHER, ROLE_STUDENT, ROLE_OFFICE}


def _model(app_label, *names):
    for name in names:
        try:
            return apps.get_model(app_label, name)
        except LookupError:
            continue
    return None


def _has_field(model, name):
    if model is None:
        return False
    try:
        model._meta.get_field(name)
        return True
    except Exception:
        return False


def _first_field(model, *names):
    return next((name for name in names if _has_field(model, name)), None)


def _queryset(model, **filters):
    if model is None:
        return None
    valid = {}
    for key, value in filters.items():
        root = key.split("__", 1)[0]
        if root.endswith("_id"):
            root = root[:-3]
        if _has_field(model, root):
            valid[key] = value
    try:
        return model._default_manager.filter(**valid)
    except (FieldError, ValueError, TypeError):
        return model._default_manager.none()


def _count(model, **filters):
    queryset = _queryset(model, **filters)
    return queryset.count() if queryset is not None else 0


def _active_year_filter(model):
    year_field = _first_field(model, "academic_year")
    if not year_field:
        return {}
    year_model = model._meta.get_field(year_field).related_model
    if year_model and _has_field(year_model, "is_active"):
        return {f"{year_field}__is_active": True}
    return {}


def _teacher_scope(user):
    teacher_model = _model("academics", "Teacher")
    assignment_model = _model("academics", "TeacherAssignment")
    if teacher_model is None or assignment_model is None or not _has_field(teacher_model, "user"):
        return [], None
    teacher = teacher_model._default_manager.filter(user=user).first()
    if teacher is None or not _has_field(assignment_model, "teacher"):
        return [], teacher
    classroom_field = _first_field(assignment_model, "classroom", "class")
    if not classroom_field:
        return [], teacher
    filters = {"teacher": teacher}
    filters.update(_active_year_filter(assignment_model))
    try:
        ids = list(
            assignment_model._default_manager.filter(**filters)
            .values_list(f"{classroom_field}_id", flat=True)
            .distinct()
        )
    except (FieldError, ValueError, TypeError):
        ids = []
    return ids, teacher


def _student_scope(user):
    student_model = _model("academics", "Student")
    enrollment_model = _model("academics", "Enrollment")
    if student_model is None or enrollment_model is None or not _has_field(student_model, "user"):
        return None, []
    student_filters = {"user": user}
    if _has_field(student_model, "is_active"):
        student_filters["is_active"] = True
    student = student_model._default_manager.filter(**student_filters).first()
    if student is None:
        return None, []
    classroom_field = _first_field(enrollment_model, "classroom", "class")
    student_field = _first_field(enrollment_model, "student")
    if not classroom_field or not student_field:
        return student, []
    filters = {student_field: student}
    filters.update(_active_year_filter(enrollment_model))
    status_field = _first_field(enrollment_model, "status")
    if status_field:
        filters[status_field] = "active"
    class_ids = list(
        _queryset(enrollment_model, **filters)
        .values_list(f"{classroom_field}_id", flat=True)
        .distinct()
    )
    return student, class_ids


def _student_count(user, role, class_ids):
    student_model = _model("academics", "Student")
    enrollment_model = _model("academics", "Enrollment")
    if role == ROLE_STUDENT:
        return int(
            student_model is not None
            and student_model._default_manager.filter(user=user, is_active=True).exists()
        )
    if role != ROLE_TEACHER:
        return _count(student_model, is_active=True)
    if enrollment_model is None or not class_ids:
        return 0
    classroom_field = _first_field(enrollment_model, "classroom", "class")
    student_field = _first_field(enrollment_model, "student")
    if not classroom_field or not student_field:
        return 0
    filters = {f"{classroom_field}_id__in": class_ids, **_active_year_filter(enrollment_model)}
    if student_model and _has_field(student_model, "is_active"):
        filters[f"{student_field}__is_active"] = True
    status_field = _first_field(enrollment_model, "status")
    if status_field:
        try:
            choices = enrollment_model._meta.get_field(status_field).choices
        except Exception:
            choices = ()
        if any(value == "active" for value, _label in choices):
            filters[status_field] = "active"
    queryset = _queryset(enrollment_model, **filters)
    return queryset.values(f"{student_field}_id").distinct().count() if queryset is not None else 0


def _active_teacher_count():
    teacher_model = _model("academics", "Teacher")
    if _has_field(teacher_model, "is_active"):
        return _count(teacher_model, is_active=True)
    if _has_field(teacher_model, "user"):
        return _count(teacher_model, user__is_active=True)
    return _count(teacher_model)


def _money_total(model, amount_field, filters=None):
    queryset = _queryset(model, **(filters or {}))
    if queryset is None or not amount_field:
        return Decimal("0.00")
    try:
        return queryset.aggregate(total=Sum(amount_field))["total"] or Decimal("0.00")
    except (FieldError, ValueError, TypeError):
        return Decimal("0.00")


def build_dashboard_context(user, *, report_start=None, report_end=None):
    role = getattr(user, "role", "")
    today = timezone.localdate()
    class_ids, teacher = _teacher_scope(user) if role == ROLE_TEACHER else ([], None)
    student, student_class_ids = _student_scope(user) if role == ROLE_STUDENT else (None, [])
    if role == ROLE_STUDENT:
        class_ids = student_class_ids
    classroom_model = _model("academics", "Classroom")
    if role in (ROLE_PRINCIPAL, ROLE_OFFICE) and classroom_model is not None:
        class_ids = list(
            _queryset(classroom_model, academic_year__is_active=True)
            .values_list("pk", flat=True)
        )
    classrooms = (
        list(_queryset(classroom_model, pk__in=class_ids).select_related("academic_year"))
        if classroom_model is not None and class_ids
        else []
    )
    context = {
        "role": role,
        "today": today,
        "report_start": report_start,
        "report_end": report_end,
        "teacher": teacher,
        "student_profile": student,
        "classrooms": classrooms,
        "class_count": len(class_ids),
        "active_students": _student_count(user, role, class_ids),
        "active_teachers": 0 if role in (ROLE_TEACHER, ROLE_STUDENT) else _active_teacher_count(),
        "attendance": {"present": 0, "absent": 0, "late": 0, "total": 0},
        "upcoming_homework": [],
        "recent_exams": [],
        "student_results": [],
        "fee_charged": Decimal("0.00"),
        "fee_paid": Decimal("0.00"),
        "fee_balance": Decimal("0.00"),
        "report_mode": report_start is not None or report_end is not None,
    }

    attendance_model = _model("attendance", "AttendanceRecord", "Attendance")
    attendance_filters = {}
    attendance_date = _first_field(attendance_model, "date", "attendance_date")
    if attendance_date:
        if report_start or report_end:
            if report_start and report_end:
                attendance_filters[f"{attendance_date}__range"] = (report_start, report_end)
            elif report_start:
                attendance_filters[f"{attendance_date}__gte"] = report_start
            else:
                attendance_filters[f"{attendance_date}__lte"] = report_end
        else:
            attendance_filters[attendance_date] = today
    if role in (ROLE_TEACHER, ROLE_STUDENT):
        class_field = _first_field(attendance_model, "classroom", "class")
        if class_field:
            attendance_filters[f"{class_field}_id__in"] = class_ids
        elif _has_field(attendance_model, "enrollment"):
            attendance_filters["enrollment__classroom_id__in"] = class_ids
        else:
            attendance_model = None
        if role == ROLE_STUDENT:
            if student is None:
                attendance_model = None
            else:
                attendance_filters["enrollment__student_id"] = student.pk
    status_field = _first_field(attendance_model, "status")
    if status_field:
        for status in ("present", "absent", "late"):
            context["attendance"][status] = _count(
                attendance_model,
                **{**attendance_filters, status_field: status},
            )
        context["attendance"]["total"] = sum(context["attendance"][status] for status in ("present", "absent", "late"))
    else:
        context["attendance"]["total"] = _count(attendance_model, **attendance_filters)

    homework_model = _model("homework", "Homework")
    due_field = _first_field(homework_model, "due_date", "due_on", "deadline")
    if due_field:
        hw_filters = {f"{due_field}__gte": report_start or today}
        if report_end:
            hw_filters[f"{due_field}__lte"] = report_end
        if role in (ROLE_TEACHER, ROLE_STUDENT):
            class_field = _first_field(homework_model, "classroom", "class")
            hw_filters[f"{class_field}_id__in" if class_field else "id__in"] = class_ids if class_field else []
        homework_qs = _queryset(homework_model, **hw_filters)
        if homework_qs is not None:
            context["upcoming_homework"] = list(homework_qs.order_by(due_field)[:5])

    if role == ROLE_PRINCIPAL:
        exam_model = _model("assessments", "Exam")
        exam_date = _first_field(exam_model, "date", "exam_date", "start_date")
        if exam_model:
            try:
                exam_filters = {}
                if exam_date and report_start:
                    exam_filters[f"{exam_date}__gte"] = report_start
                if exam_date and report_end:
                    exam_filters[f"{exam_date}__lte"] = report_end
                exams = _queryset(exam_model, **exam_filters)
                if exam_date:
                    exams = exams.order_by(f"-{exam_date}")
                context["recent_exams"] = list(exams[:5]) if exams is not None else []
                _add_result_summaries(context["recent_exams"])
            except (FieldError, ValueError, TypeError):
                context["recent_exams"] = []
    elif role == ROLE_STUDENT and student is not None:
        mark_model = _model("assessments", "StudentMark", "Mark")
        if mark_model is not None:
            context["student_results"] = list(
                _queryset(mark_model, student=student)
                .select_related("exam", "subject")
                .order_by("-exam__date")[:5]
            )

    if role in (ROLE_PRINCIPAL, ROLE_OFFICE):
        charge_model = _model("fees", "FeeCharge", "Charge")
        payment_model = _model("fees", "FeePayment", "Payment")
        charge_amount = _first_field(charge_model, "amount", "total_amount")
        payment_amount = _first_field(payment_model, "amount", "paid_amount")
        context["fee_charged"] = _money_total(charge_model, charge_amount)
        context["fee_paid"] = _money_total(payment_model, payment_amount)
        context["fee_balance"] = context["fee_charged"] - context["fee_paid"]

    return context


def _add_result_summaries(exams):
    if not exams:
        return
    result_model = _model("assessments", "Mark", "Result", "ExamResult")
    exam_field = _first_field(result_model, "exam")
    score_field = _first_field(result_model, "marks_awarded", "marks_obtained", "score", "marks")
    if not exam_field or not score_field:
        return
    try:
        summaries = result_model._default_manager.filter(
            **{f"{exam_field}_id__in": [exam.pk for exam in exams]}
        ).values(f"{exam_field}_id").annotate(
            result_count=Count("pk"),
            average_score=Avg(score_field),
        )
    except (FieldError, ValueError, TypeError):
        return
    by_exam = {item[f"{exam_field}_id"]: item for item in summaries}
    for exam in exams:
        summary = by_exam.get(exam.pk, {})
        exam.dashboard_result_count = summary.get("result_count", 0)
        exam.dashboard_average_score = summary.get("average_score")


@login_required
def index(request):
    role = getattr(request.user, "role", "")
    if role not in ALLOWED_ROLES:
        raise PermissionDenied
    context = build_dashboard_context(request.user)
    return render(request, "dashboard/index.html", context)


@login_required
def reports(request):
    role = getattr(request.user, "role", "")
    if role not in ALLOWED_ROLES:
        raise PermissionDenied
    start = _parse_date(request.GET.get("start"))
    end = _parse_date(request.GET.get("end"))
    if start and end and start > end:
        start, end = end, start
    context = build_dashboard_context(request.user, report_start=start, report_end=end)
    return render(request, "dashboard/reports.html", context)


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None
