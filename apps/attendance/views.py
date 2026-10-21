from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.academics.models import Classroom, Enrollment, Subject, TeacherAssignment
from .forms import AttendanceFilterForm, AttendanceRowFormSet, MonthFilterForm
from .models import AttendanceRecord


REVIEW_ROLES = {"principal", "office"}
EDIT_ROLES = {"principal", "teacher"}


def _role(user):
    return getattr(user, "role", None)


def _accessible_classrooms(user):
    classrooms = Classroom.objects.all()
    if _role(user) == "teacher":
        return classrooms.filter(
            pk__in=TeacherAssignment.objects.filter(
                teacher__user=user,
            ).values_list("classroom_id", flat=True)
        ).distinct()
    if _role(user) in REVIEW_ROLES | {"principal"}:
        return classrooms
    raise PermissionDenied


def _accessible_subjects(user, classroom=None):
    subjects = Subject.objects.all()
    if _role(user) == "teacher":
        assignments = TeacherAssignment.objects.filter(teacher__user=user)
        if classroom is not None:
            assignments = assignments.filter(classroom=classroom)
        return subjects.filter(pk__in=assignments.values_list("subject_id", flat=True)).distinct()
    if _role(user) in REVIEW_ROLES | {"principal"}:
        return subjects
    raise PermissionDenied


def _can_access_context(user, classroom, subject=None):
    if classroom.pk not in _accessible_classrooms(user).values_list("pk", flat=True):
        return False
    if _role(user) == "teacher":
        if subject is None:
            return False
        return TeacherAssignment.objects.filter(
            teacher__user=user,
            classroom=classroom,
            subject=subject,
        ).exists()
    return _role(user) in REVIEW_ROLES | {"principal"}


def _active_enrollments(classroom):
    return Enrollment.objects.filter(
        classroom=classroom,
        status=Enrollment.Status.ACTIVE,
    ).select_related("student", "academic_year").order_by(
        "student__last_name", "student__first_name"
    )


def _form_options(request):
    classrooms = _accessible_classrooms(request.user)
    subjects = _accessible_subjects(request.user)
    return classrooms, subjects


@login_required
def entry(request):
    if _role(request.user) not in EDIT_ROLES:
        raise PermissionDenied
    classrooms, subjects = _form_options(request)
    require_subject = _role(request.user) == "teacher"
    filter_form = AttendanceFilterForm(
        request.POST if request.method == "POST" else (request.GET or None),
        classrooms=classrooms,
        subjects=subjects,
        require_subject=require_subject,
    )
    if not filter_form.is_valid():
        return render(request, "attendance/entry.html", {"filter_form": filter_form})

    classroom = filter_form.cleaned_data["classroom"]
    subject = filter_form.cleaned_data["subject"]
    attendance_date = filter_form.cleaned_data["date"]
    if not _can_access_context(request.user, classroom, subject):
        raise PermissionDenied

    if request.method == "POST":
        enrollments = _active_enrollments(classroom)
        formset = AttendanceRowFormSet(
            request.POST,
            form_kwargs={"enrollments": enrollments},
        )
        if formset.is_valid():
            submitted_ids = {form.cleaned_data["enrollment"].pk for form in formset.forms}
            roster_ids = set(enrollments.values_list("pk", flat=True))
            if len(formset.forms) != len(roster_ids) or submitted_ids != roster_ids:
                formset._non_form_errors.append(
                    "The roster changed or contains an invalid enrollment. Reload and try again."
                )
            else:
                try:
                    with transaction.atomic():
                        for form in formset:
                            enrollment = form.cleaned_data["enrollment"]
                            record, created = AttendanceRecord.objects.get_or_create(
                                enrollment=enrollment,
                                date=attendance_date,
                                defaults={
                                    "status": form.cleaned_data["status"],
                                    "recorded_by": request.user,
                                },
                            )
                            if not created and record.status != form.cleaned_data["status"]:
                                record.status = form.cleaned_data["status"]
                                record._changed_by = request.user
                                record._correction_reason = "Corrected through daily attendance entry."
                                record.save(update_fields=("status", "updated_at"))
                except IntegrityError:
                    messages.error(request, "Attendance changed concurrently. Reload the page before saving again.")
                else:
                    messages.success(request, "Attendance saved.")
                    query = f"?classroom={classroom.pk}&subject={subject.pk if subject else ''}&date={attendance_date.isoformat()}"
                    return redirect(f"{reverse('attendance:entry')}{query}")
    else:
        enrollments = _active_enrollments(classroom)
        records = AttendanceRecord.objects.filter(
            enrollment__in=enrollments,
            date=attendance_date,
        )
        status_by_enrollment = {record.enrollment_id: record.status for record in records}
        formset = AttendanceRowFormSet(
            initial=[
                {"enrollment": enrollment.pk, "status": status_by_enrollment.get(enrollment.pk, "present")}
                for enrollment in enrollments
            ],
            form_kwargs={"enrollments": enrollments},
        )

    return render(
        request,
        "attendance/entry.html",
        {
            "filter_form": filter_form,
            "formset": formset,
            "classroom": classroom,
            "subject": subject,
            "attendance_date": attendance_date,
            "roster_rows": zip(_active_enrollments(classroom), formset.forms),
        },
    )


@login_required
def monthly_summary(request):
    if _role(request.user) not in REVIEW_ROLES | {"teacher"}:
        raise PermissionDenied
    classrooms, subjects = _form_options(request)
    require_subject = _role(request.user) == "teacher"
    form = MonthFilterForm(
        request.GET or None,
        classrooms=classrooms,
        subjects=subjects,
        require_subject=require_subject,
    )
    if not form.is_valid():
        return render(request, "attendance/summary.html", {"form": form})

    classroom = form.cleaned_data["classroom"]
    subject = form.cleaned_data["subject"]
    start_date, end_date = form.cleaned_data["month"]
    if not _can_access_context(request.user, classroom, subject):
        raise PermissionDenied

    records = AttendanceRecord.objects.filter(
        enrollment__classroom=classroom,
        date__range=(start_date, end_date),
    )
    if _role(request.user) == "teacher":
        records = records.filter(
            enrollment__classroom__in=TeacherAssignment.objects.filter(
                teacher__user=request.user,
                subject=subject,
            ).values("classroom")
        )
    days = records.values("date").annotate(
        present=Count("pk", filter=Q(status=AttendanceRecord.Status.PRESENT)),
        absent=Count("pk", filter=Q(status=AttendanceRecord.Status.ABSENT)),
        late=Count("pk", filter=Q(status=AttendanceRecord.Status.LATE)),
    ).order_by("date")
    totals = records.aggregate(
        present=Count("pk", filter=Q(status=AttendanceRecord.Status.PRESENT)),
        absent=Count("pk", filter=Q(status=AttendanceRecord.Status.ABSENT)),
        late=Count("pk", filter=Q(status=AttendanceRecord.Status.LATE)),
    )
    return render(
        request,
        "attendance/summary.html",
        {
            "form": form,
            "classroom": classroom,
            "month_start": start_date,
            "month_label": start_date.strftime("%B %Y"),
            "days": days,
            "totals": totals,
        },
    )
