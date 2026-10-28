from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.academics.models import Enrollment, Student
from apps.academics.timetable import build_grid, day_periods, is_in_progress, next_period, school_hours
from apps.assessments.models import Exam, ExamSubject, StudentMark
from apps.assessments.results import class_results
from apps.attendance.models import AttendanceRecord
from apps.homework.models import Homework, HomeworkCompletion

from .forms import StudentProfileForm
from .services import attendance_summary, fee_overview, notifications_for

NEW_NOTIFICATION_DAYS = 7
PARENT_CHILD_SESSION_KEY = "portal_child"


class Portal:
    """The signed-in student and their current class."""

    def __init__(self, request, student):
        self.request = request
        self.student = student
        self.now = timezone.localtime()
        self.today = self.now.date()
        self.enrollment = (
            Enrollment.objects.filter(
                student=student,
                status=Enrollment.Status.ACTIVE,
                academic_year__is_active=True,
            )
            .select_related("classroom__academic_year", "classroom__class_teacher__user", "academic_year")
            .first()
        )
        self.classroom = self.enrollment.classroom if self.enrollment else None
        self.children = []
        self.year = self.enrollment.academic_year if self.enrollment else None

    def render(self, template, section, context=None):
        notifications = notifications_for(self.classroom)
        base = {
            "student": self.student,
            "enrollment": self.enrollment,
            "classroom": self.classroom,
            "year": self.year,
            "section": section,
            "now": self.now,
            "school_name": settings.SCHOOL_NAME,
            "children": self.children,
            "is_parent": getattr(self.request.user, "role", None) == "parent",
            "new_notifications": notifications.filter(
                created_at__gte=self.now - timedelta(days=NEW_NOTIFICATION_DAYS)
            ).count(),
            "due_homework": Homework.objects.filter(
                classroom=self.classroom, due_date__gte=self.today
            ).count() if self.classroom else 0,
        }
        base.update(context or {})
        return render(self.request, f"student_portal/{template}", base)

    def up_next(self):
        if self.classroom is None:
            return None
        entry, date = next_period(self.classroom, self.now)
        if entry is None:
            return None
        if date == self.today:
            when = "Now" if is_in_progress(entry, date, self.now) else "Today"
        elif date == self.today + timedelta(days=1):
            when = "Tomorrow"
        else:
            when = entry.get_day_display()
        return {"entry": entry, "date": date, "when": when}


def student_portal_view(view_func):
    @login_required
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        role = getattr(request.user, "role", None)
        children = []
        if role == "student":
            student = Student.objects.filter(user=request.user, is_active=True).first()
        elif role == "parent":
            children = list(
                Student.objects.filter(guardian_user=request.user, is_active=True).order_by("first_name")
            )
            selected = request.session.get(PARENT_CHILD_SESSION_KEY)
            student = next((child for child in children if child.pk == selected), children[0] if children else None)
        else:
            return redirect("dashboard:index")
        if student is None:
            return render(request, "student_portal/not_linked.html", status=403)
        portal = Portal(request, student)
        portal.children = children
        return view_func(request, portal, *args, **kwargs)

    return wrapped


@login_required
@require_POST
def switch_child(request):
    """Let a parent with several children choose whose portal to view."""
    if getattr(request.user, "role", None) != "parent":
        return redirect("dashboard:index")
    child = Student.objects.filter(
        pk=request.POST.get("student"), guardian_user=request.user, is_active=True
    ).first()
    if child is not None:
        request.session[PARENT_CHILD_SESSION_KEY] = child.pk
    return redirect("student_portal:home")


@student_portal_view
def home(request, portal):
    today_periods = (
        day_periods(portal.classroom, portal.today.weekday()) if portal.classroom else []
    )
    homework = []
    if portal.classroom:
        homework = list(
            Homework.objects.filter(classroom=portal.classroom, due_date__gte=portal.today)
            .select_related("subject")
            .order_by("due_date")[:3]
        )
    return portal.render(
        "home.html",
        "home",
        {
            "up_next": portal.up_next(),
            "today_periods": today_periods,
            "attendance": attendance_summary(portal.enrollment),
            "homework": homework,
            "latest_notification": notifications_for(portal.classroom).first(),
        },
    )


@student_portal_view
def classroom(request, portal):
    context = {"attendance": attendance_summary(portal.enrollment)}
    if portal.classroom:
        classroom = portal.classroom
        context.update(
            {
                "up_next": portal.up_next(),
                "grid": build_grid(
                    classroom.timetable_entries.select_related("subject", "teacher__user")
                ),
                "today_weekday": portal.today.weekday(),
                "hours": school_hours(classroom),
                "subject_teachers": classroom.teacher_assignments.select_related(
                    "subject", "teacher__user"
                ).order_by("subject__name"),
                "homework": list(
                    Homework.objects.filter(classroom=classroom)
                    .select_related("subject", "assigned_by")
                    .order_by("-due_date")[:8]
                ),
                "pending_homework": Homework.objects.filter(
                    classroom=classroom, due_date__gte=portal.today
                ).count(),
                "guide_count": classroom.study_guides.count(),
                "results": _latest_results(portal),
                "recent_attendance": AttendanceRecord.objects.filter(
                    enrollment=portal.enrollment
                ).order_by("-date")[:10],
            }
        )
    return portal.render("classroom.html", "classroom", context)


@student_portal_view
def homework(request, portal):
    upcoming, past, subjects, selected = [], [], [], None
    if portal.classroom:
        items = Homework.objects.filter(classroom=portal.classroom).select_related(
            "subject", "assigned_by"
        )
        subjects = sorted({item.subject for item in items}, key=lambda subject: subject.name)
        selected = next((s for s in subjects if str(s.pk) == request.GET.get("subject")), None)
        if selected:
            items = items.filter(subject=selected)
        upcoming = list(items.filter(due_date__gte=portal.today).order_by("due_date", "subject__name"))
        for item in upcoming:
            item.days_left = (item.due_date - portal.today).days
        past = list(items.filter(due_date__lt=portal.today).order_by("-due_date")[:20])
        checks = dict(
            HomeworkCompletion.objects.filter(
                student=portal.student, homework__in=upcoming + past
            ).values_list("homework_id", "is_done")
        )
        for item in upcoming + past:
            item.checked_done = checks.get(item.pk)
    return portal.render(
        "homework.html",
        "homework",
        {"upcoming": upcoming, "past": past, "subjects": subjects, "selected_subject": selected},
    )


@student_portal_view
def homework_detail(request, portal, pk):
    if portal.classroom is None:
        raise Http404
    item = get_object_or_404(
        Homework.objects.select_related("subject", "assigned_by"),
        pk=pk,
        classroom=portal.classroom,
    )
    item.days_left = (item.due_date - portal.today).days
    check = HomeworkCompletion.objects.filter(homework=item, student=portal.student).first()
    return portal.render("homework_detail.html", "homework", {"item": item, "check": check})


def _latest_results(portal):
    exam = (
        Exam.objects.filter(classroom=portal.classroom, marks__student=portal.student, results_published=True)
        .distinct()
        .order_by("-date")
        .first()
    )
    if exam is None:
        return None
    maximums = {item.subject_id: item.maximum_marks for item in exam.subjects.all()}
    marks = list(
        StudentMark.objects.filter(exam=exam, student=portal.student)
        .select_related("subject")
        .order_by("subject__name")
    )
    rows = [
        {"subject": mark.subject, "marks": mark.marks_awarded, "maximum": maximums.get(mark.subject_id)}
        for mark in marks
    ]
    obtained = sum(row["marks"] for row in rows)
    total = sum(row["maximum"] or 0 for row in rows)
    return {
        "exam": exam,
        "rows": rows,
        "obtained": obtained,
        "total": total,
        "percent": round(obtained * 100 / total) if total else None,
    }


@student_portal_view
def study_guides(request, portal):
    guides = []
    if portal.classroom:
        guides = portal.classroom.study_guides.select_related("subject")
    return portal.render("study_guides.html", "guides", {"guides": guides})


@student_portal_view
def balance(request, portal):
    overview = fee_overview(portal.student, portal.year, portal.today) if portal.year else None
    return portal.render("balance.html", "balance", {"fees": overview})


@student_portal_view
def id_card(request, portal):
    return portal.render(
        "id_card.html",
        "id_card",
        {
            "hours": school_hours(portal.classroom) if portal.classroom else None,
            "campus": settings.SCHOOL_CAMPUS,
            "school_contact": settings.SCHOOL_CONTACT,
        },
    )


@student_portal_view
def profile(request, portal):
    return portal.render("profile.html", "profile")


@student_portal_view
def profile_edit(request, portal):
    form = StudentProfileForm(request.POST or None, request.FILES or None, instance=portal.student)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile has been updated.")
        return redirect("student_portal:profile")
    return portal.render("profile_edit.html", "profile", {"form": form})


@student_portal_view
def notifications(request, portal):
    items = list(notifications_for(portal.classroom).select_related("classroom")[:50])
    cutoff = portal.now - timedelta(days=NEW_NOTIFICATION_DAYS)
    for item in items:
        item.is_new = item.created_at >= cutoff
    return portal.render("notifications.html", "notifications", {"notifications": items})


@student_portal_view
def exams(request, portal):
    papers, published = [], []
    if portal.classroom:
        papers = list(
            ExamSubject.objects.filter(exam__classroom=portal.classroom, paper_date__gte=portal.today)
            .select_related("exam", "subject")
            .order_by("paper_date", "start_time")
        )
        published = list(
            Exam.objects.filter(classroom=portal.classroom, results_published=True).order_by("-date", "-pk")
        )
    return portal.render("exams.html", "exams", {"papers": papers, "published": published})


@student_portal_view
def result_card(request, portal, exam_id):
    exam = get_object_or_404(
        Exam.objects.select_related("classroom", "academic_year"),
        pk=exam_id,
        classroom=portal.classroom,
        results_published=True,
    )
    result = class_results(exam)
    row = next((row for row in result["rows"] if row["student"].pk == portal.student.pk), None)
    if row is None:
        raise Http404
    return portal.render("result_card.html", "exams", {"exam": exam, "result": result, "row": row})
