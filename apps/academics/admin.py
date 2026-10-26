from django.contrib import admin

from .models import (
    AcademicYear,
    Classroom,
    Enrollment,
    Student,
    Subject,
    Teacher,
    TeacherAssignment,
    TimetableEntry,
)


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("admission_number", "first_name", "last_name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("admission_number", "first_name", "last_name", "guardian_name")


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ("name", "section", "academic_year", "class_teacher")
    list_filter = ("academic_year",)
    search_fields = ("name", "section")


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "classroom", "academic_year", "status")
    list_filter = ("academic_year", "status", "classroom")
    search_fields = ("student__admission_number", "student__first_name", "student__last_name")


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ("user",)
    search_fields = ("user__username", "user__first_name", "user__last_name")


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("name", "code")
    search_fields = ("name", "code")


@admin.register(TeacherAssignment)
class TeacherAssignmentAdmin(admin.ModelAdmin):
    list_display = ("teacher", "classroom", "subject")
    list_filter = ("classroom__academic_year", "classroom", "subject")
    search_fields = ("teacher__user__username", "classroom__name", "subject__name")


@admin.register(TimetableEntry)
class TimetableEntryAdmin(admin.ModelAdmin):
    list_display = ("classroom", "day", "start_time", "end_time", "subject", "teacher", "label")
    list_filter = ("classroom__academic_year", "classroom", "day")
