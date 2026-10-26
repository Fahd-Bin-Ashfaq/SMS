from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import AcademicYearForm, ClassroomForm, StudentForm, TimetableEntryForm
from .models import AcademicYear, Classroom, Enrollment, Student, TeacherAssignment, TimetableEntry
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
