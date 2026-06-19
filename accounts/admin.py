from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from accounts.models import User, OTP, Device, AuthEvent, ISafePassLink


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ('username', 'email', 'phone', 'role', 'is_verified', 'is_active', 'created_at')
    list_filter = ('role', 'is_verified', 'is_active')
    search_fields = ('username', 'email', 'phone')
    fieldsets = DjangoUserAdmin.fieldsets + (
        ('SecDrive', {
            'fields': (
                'uuid', 'phone', 'role', 'is_verified', 'google_linked',
                'failed_login_count', 'locked_until',
            )
        }),
    )
    readonly_fields = ('uuid',)


@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ('user', 'purpose', 'channel', 'is_used', 'attempts', 'created_at', 'expires_at')
    list_filter = ('purpose', 'channel', 'is_used')
    search_fields = ('user__username', 'user__email', 'user__phone')


@admin.register(Device)
class DeviceAdmin(admin.ModelAdmin):
    list_display = ('user', 'device_id', 'platform', 'is_trusted', 'is_active', 'last_login_at')
    list_filter = ('platform', 'is_trusted', 'is_active')
    search_fields = ('user__username', 'device_id')


@admin.register(AuthEvent)
class AuthEventAdmin(admin.ModelAdmin):
    list_display = ('user', 'event_type', 'identifier_tried', 'ip_address', 'created_at')
    list_filter = ('event_type',)
    search_fields = ('user__username', 'identifier_tried', 'ip_address')


@admin.register(ISafePassLink)
class ISafePassLinkAdmin(admin.ModelAdmin):
    list_display = ('user', 'isafepass_user_id', 'linked_at')
    search_fields = ('user__username', 'isafepass_user_id')
