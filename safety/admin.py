from django.contrib import admin

from safety.models import TrustedContact


@admin.register(TrustedContact)
class TrustedContactAdmin(admin.ModelAdmin):
    list_display = ['id', 'owner', 'contact_type', 'relationship', 'name', 'phone', 'email',
                    'is_primary_emergency', 'notify_on_journey']
    list_filter = ['contact_type', 'relationship']
    search_fields = ['owner__username', 'name', 'phone', 'email']
    readonly_fields = ['id', 'created_at', 'updated_at']
