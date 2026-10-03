from django.contrib import admin

from apps.notifications.models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('receiver', 'role', 'title', 'read', 'created_at')
    list_filter = ('role', 'read')
