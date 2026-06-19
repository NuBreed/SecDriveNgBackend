from django.contrib import admin

from common.admin_mixins import ReviewAdminMixin
from operators.models import OperatorVerification
from operators import services


@admin.register(OperatorVerification)
class OperatorVerificationAdmin(ReviewAdminMixin, admin.ModelAdmin):
    review_service = services

    list_display = ('organization_name', 'cac_number', 'user', 'status_badge', 'is_verified', 'submitted_at')
    list_filter = ('status', 'is_verified')
    search_fields = ('organization_name', 'cac_number', 'user__username')
    readonly_fields = ('status_badge', 'documents', 'submitted_at', 'reviewed_at',
                       'reviewed_by', 'updated_at')
    fieldsets = (
        ('Organization', {'fields': ('user', 'organization_name', 'cac_number',
                                    'contact_info', 'certification_expiry', 'documents')}),
        ('Review', {'fields': ('status', 'status_badge', 'is_verified', 'rejection_reason',
                               'submitted_at', 'reviewed_at', 'reviewed_by', 'updated_at')}),
    )
