from django.contrib import admin

from notifications.models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'type', 'title', 'read', 'created_at')
    list_filter = ('type', 'read')
    search_fields = ('user__username', 'title')
    readonly_fields = ('created_at',)
