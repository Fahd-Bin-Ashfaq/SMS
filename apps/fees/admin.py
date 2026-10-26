from django.contrib import admin

from .models import FeeCharge, FeePayment


@admin.register(FeeCharge)
class FeeChargeAdmin(admin.ModelAdmin):
    list_display = ("student", "category", "description", "academic_year", "amount", "due_date", "created_by")
    list_filter = ("academic_year", "due_date")
    search_fields = ("student__admission_number", "student__first_name", "student__last_name", "description")
    readonly_fields = ("created_at",)


@admin.register(FeePayment)
class FeePaymentAdmin(admin.ModelAdmin):
    list_display = ("receipt_reference", "student", "payment_date", "amount", "method", "received_by")
    list_filter = ("method", "payment_date", "academic_year")
    search_fields = ("receipt_reference", "student__admission_number", "student__first_name", "student__last_name")
    readonly_fields = (
        "student",
        "academic_year",
        "enrollment",
        "amount",
        "payment_date",
        "method",
        "receipt_reference",
        "notes",
        "received_by",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
