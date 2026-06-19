from django.contrib import admin

from common.admin_mixins import ReviewAdminMixin
from kyc.models import IdentityVerification, ReviewEvent
from kyc.services import kyc_service


@admin.register(IdentityVerification)
class IdentityVerificationAdmin(ReviewAdminMixin, admin.ModelAdmin):
    review_service = kyc_service

    list_display = ('user', 'primary_id_type', 'status_badge', 'submitted_at', 'reviewed_at')
    list_filter = ('status', 'primary_id_type')
    search_fields = ('user__username', 'user__email', 'user__phone')
    readonly_fields = ('status_badge', 'documents', 'submitted_at', 'reviewed_at',
                       'reviewed_by', 'updated_at')
    fieldsets = (
        ('Request', {'fields': ('user', 'primary_id_type', 'documents')}),
        ('Review', {'fields': ('status', 'status_badge', 'rejection_reason',
                               'submitted_at', 'reviewed_at', 'reviewed_by', 'updated_at')}),
    )


@admin.register(ReviewEvent)
class ReviewEventAdmin(admin.ModelAdmin):
    list_display = ('action', 'actor', 'content_type', 'object_id', 'created_at')
    list_filter = ('action', 'content_type')
    search_fields = ('actor__username', 'object_id')
    readonly_fields = ('actor', 'content_type', 'object_id', 'action', 'reason', 'created_at')
