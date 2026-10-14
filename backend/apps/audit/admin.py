from django.contrib import admin

from apps.audit.models import ActivityFlag, ActivitySettings, AuditLog, SuspiciousAlert


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


@admin.register(ActivityFlag)
class ActivityFlagAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'user', 'window_start', 'window_end', 'status', 'reviewed_by')
    list_filter = ('status', 'user__role')
    search_fields = ('user__username', 'note')
    readonly_fields = ('user', 'window_start', 'window_end', 'features', 'reasons', 'eps', 'created_at')


admin.site.register(ActivitySettings)


@admin.register(SuspiciousAlert)
class SuspiciousAlertAdmin(admin.ModelAdmin):
    list_display = ('day', 'user', 'reason', 'status')
    list_filter = ('status', 'day', 'user__role')
    search_fields = ('user__username', 'reason')
    readonly_fields = ('user', 'day', 'reason', 'features', 'created_at')
    actions = ('mark_reviewed', 'mark_dismissed')

    @admin.action(description='Mark selected alerts as reviewed')
    def mark_reviewed(self, request, queryset):
        queryset.update(status=SuspiciousAlert.Status.REVIEWED)

    @admin.action(description='Mark selected alerts as dismissed')
    def mark_dismissed(self, request, queryset):
        queryset.update(status=SuspiciousAlert.Status.DISMISSED)
