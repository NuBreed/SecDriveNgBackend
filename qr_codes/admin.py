from django.contrib import admin
from django.utils import timezone

from qr_codes.models import QRCode, QRScan


@admin.register(QRCode)
class QRCodeAdmin(admin.ModelAdmin):
    list_display = ['id', 'entity_type', 'content_object', 'status', 'generation', 'generated_at', 'revoked_at']
    list_filter = ['entity_type', 'status']
    search_fields = ['id', 'object_id', 'token']
    readonly_fields = ['id', 'token', 'generated_at', 'revoked_at', 'generation']
    actions = ['revoke_selected']

    @admin.action(description='Revoke selected QR codes')
    def revoke_selected(self, request, queryset):
        updated = queryset.filter(status=QRCode.Status.ACTIVE).update(
            status=QRCode.Status.REVOKED,
            revoked_at=timezone.now(),
            revoked_by=request.user,
            revoke_reason='Bulk admin revocation',
        )
        self.message_user(request, f'{updated} QR code(s) revoked.')


@admin.register(QRScan)
class QRScanAdmin(admin.ModelAdmin):
    list_display = ['id', 'qr_code', 'scanned_by', 'result', 'ip_address', 'scanned_at']
    list_filter = ['result']
    search_fields = ['token_tried', 'ip_address']
    readonly_fields = [f.name for f in QRScan._meta.get_fields() if hasattr(f, 'name')]
