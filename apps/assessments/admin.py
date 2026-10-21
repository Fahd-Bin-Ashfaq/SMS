from django.contrib import admin

from apps.assessments.models import Exam, ExamSubject, MarkChange, StudentMark


class ExamSubjectInline(admin.TabularInline):
    model = ExamSubject
    extra = 1


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ("name", "classroom", "academic_year", "date")
    list_filter = ("academic_year", "classroom")
    search_fields = ("name", "classroom__name")
    inlines = (ExamSubjectInline,)


@admin.register(ExamSubject)
class ExamSubjectAdmin(admin.ModelAdmin):
    list_display = ("exam", "subject", "maximum_marks")
    list_filter = ("exam__academic_year", "subject")


@admin.register(StudentMark)
class StudentMarkAdmin(admin.ModelAdmin):
    list_display = ("student", "exam", "subject", "marks_awarded", "updated_at")
    list_filter = ("exam__academic_year", "exam", "subject")
    search_fields = ("student__admission_number", "student__first_name", "student__last_name")
    readonly_fields = ("updated_at",)

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(MarkChange)
class MarkChangeAdmin(admin.ModelAdmin):
    list_display = ("mark", "previous_marks", "new_marks", "changed_by", "changed_at")
    list_filter = ("changed_at",)
    readonly_fields = (
        "mark",
        "previous_marks",
        "new_marks",
        "changed_by",
        "changed_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
