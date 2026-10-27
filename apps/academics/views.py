import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from apps.fees.services import whatsapp_link, whatsapp_number

from .forms import AcademicYearForm, ClassroomForm, StudentForm, TimetableEntryForm
from .importer import COLUMNS as IMPORT_COLUMNS, REQUIRED as IMPORT_REQUIRED, import_students, template_csv
from .models import AcademicYear, Classroom, Enrollment, Student, TeacherAssignment, TimetableEntry
from .promotion import SKIP, copy_classes, promote, suggest_plan
from .timetable import build_grid, can_edit_timetable


MANAGER_ROLES = ("office", "principal")


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    allowed_roles = ()

    def test_func(self):
        return getattr(self.request.user, "role", None) in self.allowed_roles


class ManagerRequiredMixin(RoleRequiredMixin):
    allowed_roles = MANAGER_ROLES


class AcademicListView(RoleRequiredMixin, ListView):
    allowed_roles = ("office", "principal", "teacher")
    template_name = "academics/object_list.html"
    context_object_name = "object_list"
    page_title = ""
    create_url_name = ""

    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        if getattr(user, "role", None) in MANAGER_ROLES:
            return queryset
        if getattr(user, "role", None) != "teacher":
            return queryset.none()
        assignments = TeacherAssignment.objects.filter(teacher__user=user)
        if self.model is Classroom:
            return queryset.filter(teacher_assignments__teacher__user=user).distinct()
        if self.model is Student:
            return queryset.filter(
                enrollments__classroom__teacher_assignments__teacher__user=user,
                enrollments__status=Enrollment.Status.ACTIVE,
            ).distinct()
        if self.model is AcademicYear:
            return queryset.filter(
                classrooms__teacher_assignments__teacher__user=user
            ).distinct()
        return queryset.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["can_manage"] = getattr(self.request.user, "role", None) in MANAGER_ROLES
        context["create_url_name"] = self.create_url_name
        context["create_label"] = {
            "Classes": "class",
            "Students": "student",
            "Academic years": "academic year",
        }[self.page_title]
        return context


class ClassroomListView(AcademicListView):
    model = Classroom
    page_title = "Classes"
    create_url_name = "academics:classroom_create"


class StudentListView(AcademicListView):
    model = Student
    page_title = "Students"
    create_url_name = "academics:student_create"


class AcademicYearListView(AcademicListView):
    model = AcademicYear
    page_title = "Academic years"
    create_url_name = "academics:academic_year_create"


class ManagerCreateView(ManagerRequiredMixin, CreateView):
    template_name = "academics/object_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form_title"] = self.model._meta.verbose_name
        return context

    def get_success_url(self):
        return reverse_lazy(self.list_url_name)


class ManagerUpdateView(ManagerRequiredMixin, UpdateView):
    template_name = "academics/object_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["form_title"] = self.model._meta.verbose_name
        return context

    def get_success_url(self):
        return reverse_lazy(self.list_url_name)


class ManagerDeleteView(ManagerRequiredMixin, DeleteView):
    template_name = "academics/object_confirm_delete.html"

    def get_success_url(self):
        return reverse_lazy(self.list_url_name)


class ClassroomCreateView(ManagerCreateView):
    model = Classroom
    form_class = ClassroomForm
    list_url_name = "academics:classroom_list"


class ClassroomUpdateView(ManagerUpdateView):
    model = Classroom
    form_class = ClassroomForm
    list_url_name = "academics:classroom_list"


class ClassroomDeleteView(ManagerDeleteView):
    model = Classroom
    list_url_name = "academics:classroom_list"


class StudentCreateView(ManagerCreateView):
    model = Student
    form_class = StudentForm
    list_url_name = "academics:student_list"


class StudentUpdateView(ManagerUpdateView):
    model = Student
    form_class = StudentForm
    list_url_name = "academics:student_list"


class StudentDeleteView(ManagerDeleteView):
    model = Student
    list_url_name = "academics:student_list"


class AcademicYearCreateView(ManagerCreateView):
    model = AcademicYear
    form_class = AcademicYearForm
    list_url_name = "academics:academic_year_list"


class AcademicYearUpdateView(ManagerUpdateView):
    model = AcademicYear
    form_class = AcademicYearForm
    list_url_name = "academics:academic_year_list"


class AcademicYearDeleteView(ManagerDeleteView):
    model = AcademicYear
    list_url_name = "academics:academic_year_list"


TIMETABLE_ROLES = ("office", "principal", "teacher")


def _timetable_classrooms(user):
    classrooms = Classroom.objects.select_related("academic_year", "class_teacher__user")
    if getattr(user, "role", None) == "teacher":
        classrooms = classrooms.filter(
            Q(class_teacher__user=user) | Q(teacher_assignments__teacher__user=user)
        ).distinct()
    return classrooms.order_by("-academic_year__is_active", "name", "section")


@login_required
def timetable_index(request):
    if getattr(request.user, "role", None) not in TIMETABLE_ROLES:
        raise PermissionDenied
    classrooms = [
        (classroom, can_edit_timetable(request.user, classroom))
        for classroom in _timetable_classrooms(request.user)
    ]
    return render(request, "academics/timetable_index.html", {"classrooms": classrooms})


@login_required
def timetable_detail(request, pk):
    if getattr(request.user, "role", None) not in TIMETABLE_ROLES:
        raise PermissionDenied
    classroom = get_object_or_404(_timetable_classrooms(request.user), pk=pk)
    can_edit = can_edit_timetable(request.user, classroom)
    form = None
    if can_edit:
        form = TimetableEntryForm(request.POST or None, classroom=classroom)
        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(request, "Period added to the timetable.")
            return redirect("academics:timetable_detail", pk=classroom.pk)
    elif request.method == "POST":
        raise PermissionDenied
    entries = classroom.timetable_entries.select_related("subject", "teacher__user")
    return render(
        request,
        "academics/timetable_detail.html",
        {"classroom": classroom, "grid": build_grid(entries), "can_edit": can_edit, "form": form},
    )


def _editable_entry(request, pk):
    entry = get_object_or_404(TimetableEntry.objects.select_related("classroom__class_teacher"), pk=pk)
    if not can_edit_timetable(request.user, entry.classroom):
        raise PermissionDenied
    return entry


@login_required
def timetable_entry_edit(request, pk):
    entry = _editable_entry(request, pk)
    form = TimetableEntryForm(request.POST or None, instance=entry, classroom=entry.classroom)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Period updated.")
        return redirect("academics:timetable_detail", pk=entry.classroom_id)
    return render(
        request,
        "academics/timetable_entry_form.html",
        {"form": form, "entry": entry, "classroom": entry.classroom},
    )


@login_required
@require_POST
def timetable_entry_delete(request, pk):
    entry = _editable_entry(request, pk)
    classroom_id = entry.classroom_id
    entry.delete()
    messages.success(request, "Period removed.")
    return redirect("academics:timetable_detail", pk=classroom_id)


def _require_role(user, roles):
    if getattr(user, "role", None) not in roles:
        raise PermissionDenied


@login_required
def student_import(request):
    _require_role(request.user, MANAGER_ROLES)
    year = AcademicYear.objects.filter(is_active=True).first()
    result = None
    if request.method == "POST":
        uploaded = request.FILES.get("file")
        if year is None:
            messages.error(request, "Set an active academic year before importing students.")
        elif uploaded is None:
            messages.error(request, "Choose a file to upload.")
        elif uploaded.size > 5 * 1024 * 1024:
            messages.error(request, "The file is larger than 5 MB.")
        else:
            result = import_students(uploaded, year, create_classes=bool(request.POST.get("create_classes")))
            if not result.errors:
                messages.success(
                    request,
                    f"Import finished: {result.created} new student{'s' if result.created != 1 else ''}, "
                    f"{result.updated} updated"
                    + (f", {result.classes_created} new class{'es' if result.classes_created != 1 else ''}" if result.classes_created else "")
                    + ".",
                )
                return redirect("academics:student_list")
    return render(
        request,
        "academics/student_import.html",
        {"year": year, "result": result, "columns": IMPORT_COLUMNS, "required": IMPORT_REQUIRED},
    )


@login_required
def student_import_template(request):
    _require_role(request.user, MANAGER_ROLES)
    response = HttpResponse(template_csv(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="students-template.csv"'
    return response


@login_required
def promote_students(request):
    _require_role(request.user, ("principal",))
    source = AcademicYear.objects.filter(is_active=True).first()
    if source is None:
        messages.error(request, "Set an active academic year first.")
        return redirect("academics:academic_year_list")
    targets = AcademicYear.objects.filter(start_date__gt=source.start_date).order_by("start_date")
    target = targets.filter(pk=request.POST.get("target") or request.GET.get("to")).first() or targets.first()
    source_classes = list(
        Classroom.objects.filter(academic_year=source)
        .annotate(
            student_count=Count(
                "enrollments",
                filter=Q(enrollments__status=Enrollment.Status.ACTIVE, enrollments__student__is_active=True),
            )
        )
        .order_by("name", "section")
    )
    target_classes = list(Classroom.objects.filter(academic_year=target).order_by("name", "section")) if target else []

    if request.method == "POST" and target is not None:
        if request.POST.get("action") == "copy_classes":
            created = copy_classes(source, target)
            messages.success(request, f"{created} class{'es' if created != 1 else ''} copied to {target.name}.")
            return redirect(f"{reverse('academics:promote')}?to={target.pk}")
        plan = {c.pk: request.POST.get(f"class_{c.pk}", SKIP) for c in source_classes}
        repeaters = {int(pk) for pk in request.POST.getlist("repeat") if pk.isdigit()}
        result = promote(source, target, plan, repeaters, make_active=bool(request.POST.get("make_active")))
        messages.success(
            request,
            f"Done: {result.promoted} promoted, {result.repeated} repeating, {result.left} left school"
            + (f", {result.already_enrolled} were already in {target.name}" if result.already_enrolled else "")
            + "."
            + (f" {target.name} is now the active year." if request.POST.get("make_active") else ""),
        )
        return redirect("academics:student_list")

    plan = suggest_plan(source_classes, target_classes)
    students_by_class = {}
    for enrollment in Enrollment.objects.filter(
        academic_year=source, status=Enrollment.Status.ACTIVE, student__is_active=True
    ).select_related("student").order_by("student__first_name", "student__last_name"):
        students_by_class.setdefault(enrollment.classroom_id, []).append(enrollment.student)
    for classroom in source_classes:
        classroom.suggested = plan.get(classroom.pk, SKIP)
        classroom.students = students_by_class.get(classroom.pk, [])
    return render(
        request,
        "academics/promote.html",
        {
            "source": source,
            "target": target,
            "targets": targets,
            "source_classes": source_classes,
            "target_classes": target_classes,
        },
    )


PARENT_PASSWORD_CHARS = "abcdefghjkmnpqrstuvwxyz23456789"
PARENT_CREDENTIALS_SESSION_KEY = "parent_login_credentials"


def _parent_username(phone):
    """0300-1234567 / +92 300 1234567 -> 03001234567 (what parents remember)."""
    digits = whatsapp_number(phone)
    return f"0{digits[2:]}" if digits.startswith("92") else digits


def _new_parent_password():
    return "".join(secrets.choice(PARENT_PASSWORD_CHARS) for _ in range(8))


def _share_credentials(request, student, user, password):
    login_url = request.build_absolute_uri(reverse("login"))
    message = (
        f"Assalam-o-Alaikum {user.first_name or 'Parent'}, {settings.SCHOOL_NAME} parent portal login for "
        f"{student.first_name} {student.last_name}:\nUsername: {user.username}\nPassword: {password}\n{login_url}"
    )
    request.session[PARENT_CREDENTIALS_SESSION_KEY] = {
        "student": f"{student.first_name} {student.last_name}",
        "username": user.username,
        "password": password,
        "whatsapp": whatsapp_link(whatsapp_number(user.username), message),
    }


@login_required
def parent_logins(request):
    _require_role(request.user, MANAGER_ROLES)
    User = get_user_model()
    if request.method == "POST":
        student = get_object_or_404(Student, pk=request.POST.get("student"))
        action = request.POST.get("action")
        if action == "reset" and student.guardian_user_id:
            parent = student.guardian_user
            password = _new_parent_password()
            parent.set_password(password)
            parent.save(update_fields=["password"])
            _share_credentials(request, student, parent, password)
        elif action == "create":
            username = _parent_username(student.guardian_phone)
            if not username:
                messages.error(request, f"Add a valid guardian phone number for {student.first_name} first.")
            else:
                parent = User.objects.filter(username=username).first()
                if parent is not None and parent.role != "parent":
                    messages.error(request, f"The username {username} already belongs to a staff or student account.")
                elif parent is not None:
                    student.guardian_user = parent
                    student.save(update_fields=["guardian_user"])
                    messages.success(
                        request,
                        f"{student.first_name} was added to the existing parent login {username} "
                        "(brothers and sisters share one login). The password did not change.",
                    )
                else:
                    password = _new_parent_password()
                    first, _, last = (student.guardian_name or "Parent").partition(" ")
                    parent = User.objects.create_user(
                        username=username, password=password, role="parent", first_name=first, last_name=last
                    )
                    student.guardian_user = parent
                    student.save(update_fields=["guardian_user"])
                    _share_credentials(request, student, parent, password)
        elif action == "remove" and student.guardian_user_id:
            student.guardian_user = None
            student.save(update_fields=["guardian_user"])
            messages.success(request, f"Parent login removed from {student.first_name}.")
        query = request.POST.get("query", "")
        return redirect(f"{reverse('academics:parent_logins')}{'?' + query if query else ''}")

    classrooms = Classroom.objects.filter(academic_year__is_active=True).order_by("name", "section")
    selected = next((c for c in classrooms if str(c.pk) == request.GET.get("class")), None)
    enrollments = Enrollment.objects.filter(
        academic_year__is_active=True, status=Enrollment.Status.ACTIVE, student__is_active=True
    ).select_related("student__guardian_user", "classroom").order_by(
        "classroom__name", "classroom__section", "student__first_name"
    )
    if selected:
        enrollments = enrollments.filter(classroom=selected)
    return render(
        request,
        "academics/parent_logins.html",
        {
            "enrollments": enrollments,
            "classrooms": classrooms,
            "selected_class": selected,
            "credentials": request.session.pop(PARENT_CREDENTIALS_SESSION_KEY, None),
            "query": request.GET.urlencode(),
        },
    )
