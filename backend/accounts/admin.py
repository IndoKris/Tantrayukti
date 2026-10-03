"""Admin registration for the custom user model."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from accounts.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")

    # Append the EcoTrack role to Django's default fieldsets rather than
    # redefining them, so nothing from the stock admin is lost.
    fieldsets = BaseUserAdmin.fieldsets + (("EcoTrack", {"fields": ("role",)}),)
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("EcoTrack", {"fields": ("email", "role")}),
    )
