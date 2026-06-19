"""Reusable Django admin review console for verification requests.

Subclasses set ``review_service`` to a module exposing
``approve(req, admin)``, ``reject(req, admin, reason)`` and
``request_more_info(req, admin, reason)``. Provides bulk approve/reject/more-info
actions, a colour-coded status badge, and a list of attached documents with
authenticated download links.
"""
from django.contrib import admin, messages
from django.contrib.contenttypes.models import ContentType
from django.utils.html import format_html, format_html_join

from common.models import VerificationDocument
from common.admin import document_link

_STATUS_COLORS = {
    'APPROVED': '#1a7f37',
    'PENDING': '#9a6700',
    'MORE_INFO': '#9a6700',
    'REJECTED': '#cf222e',
    'SUSPENDED': '#cf222e',
    'ESCALATED': '#8250df',
    'NOT_SUBMITTED': '#57606a',
}


class ReviewAdminMixin:
    review_service = None  # module with approve/reject/request_more_info
    actions = ['approve_selected', 'reject_selected', 'request_more_info_selected']

    @admin.display(description='Status')
    def status_badge(self, obj):
        color = _STATUS_COLORS.get(obj.status, '#57606a')
        return format_html(
            '<b style="color:{}">{}</b>', color, obj.get_status_display(),
        )

    @admin.display(description='Documents')
    def documents(self, obj):
        ct = ContentType.objects.get_for_model(obj)
        docs = VerificationDocument.objects.filter(content_type=ct, object_id=str(obj.pk))
        if not docs:
            return '—'
        return format_html_join(
            ' | ', '{}', ((document_link(d),) for d in docs)
        )

    @admin.action(description='Approve selected')
    def approve_selected(self, request, queryset):
        for obj in queryset:
            self.review_service.approve(obj, admin=request.user)
        self.message_user(request, f'{queryset.count()} request(s) approved.', messages.SUCCESS)

    @admin.action(description='Reject selected (uses rejection_reason field)')
    def reject_selected(self, request, queryset):
        for obj in queryset:
            self.review_service.reject(obj, admin=request.user, reason=obj.rejection_reason or '')
        self.message_user(request, f'{queryset.count()} request(s) rejected.', messages.WARNING)

    @admin.action(description='Request more info (uses rejection_reason field)')
    def request_more_info_selected(self, request, queryset):
        for obj in queryset:
            self.review_service.request_more_info(obj, admin=request.user, reason=obj.rejection_reason or '')
        self.message_user(request, f'Requested more info on {queryset.count()} request(s).', messages.INFO)
