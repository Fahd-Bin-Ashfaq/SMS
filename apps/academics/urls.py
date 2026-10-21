from django.urls import path

from . import views

app_name = "academics"

urlpatterns = [
    path("", views.ClassroomListView.as_view(), name="index"),
    path("classes/", views.ClassroomListView.as_view(), name="classroom_list"),
    path("classes/add/", views.ClassroomCreateView.as_view(), name="classroom_create"),
    path("classes/<int:pk>/edit/", views.ClassroomUpdateView.as_view(), name="classroom_update"),
    path(
        "classes/<int:pk>/delete/",
        views.ClassroomDeleteView.as_view(),
        name="classroom_delete",
    ),
    path("students/", views.StudentListView.as_view(), name="student_list"),
    path("students/add/", views.StudentCreateView.as_view(), name="student_create"),
    path("students/<int:pk>/edit/", views.StudentUpdateView.as_view(), name="student_update"),
    path("students/<int:pk>/delete/", views.StudentDeleteView.as_view(), name="student_delete"),
    path("years/", views.AcademicYearListView.as_view(), name="academic_year_list"),
    path("years/add/", views.AcademicYearCreateView.as_view(), name="academic_year_create"),
    path(
        "years/<int:pk>/edit/",
        views.AcademicYearUpdateView.as_view(),
        name="academic_year_update",
    ),
    path(
        "years/<int:pk>/delete/",
        views.AcademicYearDeleteView.as_view(),
        name="academic_year_delete",
    ),
]
