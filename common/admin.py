from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from common.models import VerificationDocument


def document_link(doc):
    """Admin-safe link to the authenticated download endpoint for a document."""
    if doc is None or not doc.file:
        return '—'
    url = reverse('document-download', args=[doc.pk])
    label = doc.get_doc_type_display()
    if doc.is_expired:
        label += ' (EXPIRED)'
    return format_html('<a href="{}" target="_blank">{}</a>', url, label)


@admin.register(VerificationDocument)
class VerificationDocumentAdmin(admin.ModelAdmin):
    list_display = ('doc_type', 'owner', 'document_number', 'expiry_date', 'is_expired', 'uploaded_at')
    list_filter = ('doc_type',)
    search_fields = ('owner__username', 'owner__email', 'document_number')
    readonly_fields = ('uploaded_at', 'download')

    @admin.display(description='Download')
    def download(self, obj):
        return document_link(obj)

    @admin.display(boolean=True, description='Expired')
    def is_expired(self, obj):
        return obj.is_expired
