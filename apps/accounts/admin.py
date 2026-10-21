from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .forms import AccountChangeForm, AccountCreationForm
from .models import User


@admin.register(User)
class AccountAdmin(UserAdmin):
    add_form = AccountCreationForm
    form = AccountChangeForm
    model = User
    list_display = ("username", "email", "first_name", "last_name", "role", "is_active")
    list_filter = ("role", "is_active", "is_staff", "is_superuser")
    fieldsets = UserAdmin.fieldsets + (("School role", {"fields": ("role",)}),)
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Staff details", {"fields": ("email", "first_name", "last_name", "role")}),
    )
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("username",)
