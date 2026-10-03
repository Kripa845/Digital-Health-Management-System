from django.contrib import admin

from apps.audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only: audit entries are never edited or deleted."""
    list_display = ('timestamp', 'user', 'action', 'ip_address')
    list_filter = ('action',)
    search_fields = ('description', 'user__username', 'ip_address')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
