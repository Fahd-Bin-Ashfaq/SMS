from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import AcademicYearForm, ClassroomForm, StudentForm
from .models import AcademicYear, Classroom, Enrollment, Student, TeacherAssignment


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
