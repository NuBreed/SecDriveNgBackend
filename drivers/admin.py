from django.contrib import admin

from common.admin_mixins import ReviewAdminMixin
from drivers.models import Driver, DriverVerification
from drivers import services


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = ('user', 'license_number', 'verification_status', 'trust_score', 'created_at')
    list_filter = ('verification_status',)
    search_fields = ('user__username', 'user__email', 'license_number')


@admin.register(DriverVerification)
class DriverVerificationAdmin(ReviewAdminMixin, admin.ModelAdmin):
    review_service = services

    list_display = ('driver', 'license_number', 'license_expiry', 'status_badge', 'submitted_at')
    list_filter = ('status', 'background_review_passed')
    search_fields = ('driver__user__username', 'license_number')
    readonly_fields = ('status_badge', 'documents', 'submitted_at', 'reviewed_at',
                       'reviewed_by', 'updated_at')
    fieldsets = (
        ('Request', {'fields': ('driver', 'license_number', 'license_expiry',
                               'background_review_passed', 'documents')}),
        ('Review', {'fields': ('status', 'status_badge', 'rejection_reason',
                               'submitted_at', 'reviewed_at', 'reviewed_by', 'updated_at')}),
    )
