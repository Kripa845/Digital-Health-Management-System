from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from apps.users.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'first_name', 'last_name', 'role', 'is_active', 'must_change_password')
    list_filter = ('role', 'is_active', 'must_change_password')
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Mero Care Card', {'fields': ('role', 'must_change_password')}),
    )
