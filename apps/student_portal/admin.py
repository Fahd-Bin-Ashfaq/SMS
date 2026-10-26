from django.contrib import admin

from .models import Notification, StudyGuide


@admin.register(StudyGuide)
class StudyGuideAdmin(admin.ModelAdmin):
    list_display = ("title", "classroom", "subject", "uploaded_by", "created_at")
    list_filter = ("classroom", "subject")
    search_fields = ("title", "description")

    def save_model(self, request, obj, form, change):
        if not obj.uploaded_by_id:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "classroom", "created_by", "created_at")
    list_filter = ("classroom",)
    search_fields = ("title", "message")

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
