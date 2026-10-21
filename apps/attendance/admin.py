from django.contrib import admin

from .models import AttendanceCorrection, AttendanceRecord


class AttendanceCorrectionInline(admin.TabularInline):
    model = AttendanceCorrection
    extra = 0
    can_delete = False
    readonly_fields = ("changed_by", "previous_status", "new_status", "reason", "changed_at")

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("enrollment", "date", "status", "recorded_by")
    list_filter = ("date", "status", "enrollment__classroom")
    search_fields = (
        "enrollment__student__first_name",
        "enrollment__student__last_name",
        "enrollment__student__admission_number",
    )
    date_hierarchy = "date"
    readonly_fields = ("created_at", "updated_at")
    inlines = (AttendanceCorrectionInline,)

    def has_module_permission(self, request):
        return getattr(request.user, "role", None) in {"principal", "office"}

    def has_view_permission(self, request, obj=None):
        return getattr(request.user, "role", None) in {"principal", "office"}

    def has_add_permission(self, request):
        return getattr(request.user, "role", None) == "principal"

    def has_change_permission(self, request, obj=None):
        return getattr(request.user, "role", None) == "principal"

    def save_model(self, request, obj, form, change):
        if change:
            obj._changed_by = request.user
            obj._correction_reason = "Corrected in the attendance admin."
        super().save_model(request, obj, form, change)


@admin.register(AttendanceCorrection)
class AttendanceCorrectionAdmin(admin.ModelAdmin):
    list_display = ("attendance", "previous_status", "new_status", "changed_by", "changed_at")
    list_filter = ("previous_status", "new_status", "changed_at")
    readonly_fields = ("attendance", "changed_by", "previous_status", "new_status", "reason", "changed_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return getattr(request.user, "role", None) in {"principal", "office"}

    def has_module_permission(self, request):
        return getattr(request.user, "role", None) in {"principal", "office"}
