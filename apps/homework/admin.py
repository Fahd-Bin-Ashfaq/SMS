from django.contrib import admin

from apps.homework.models import Homework


@admin.register(Homework)
class HomeworkAdmin(admin.ModelAdmin):
    list_display = ("title", "classroom", "subject", "assigned_by", "assigned_date", "due_date")
    list_filter = ("classroom", "subject", "assigned_date", "due_date")
    search_fields = (
        "title",
        "description",
        "classroom__name",
        "subject__name",
        "assigned_by__username",
    )
    date_hierarchy = "assigned_date"
