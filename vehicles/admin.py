from django.contrib import admin

from common.admin_mixins import ReviewAdminMixin
from vehicles.models import Vehicle, VehicleVerification
from vehicles import services


@admin.register(Vehicle)
class VehicleAdmin(admin.ModelAdmin):
    list_display = ('registration_number', 'brand', 'model', 'year', 'owner', 'is_verified')
    list_filter = ('is_verified', 'vehicle_type')
    search_fields = ('registration_number', 'brand', 'model', 'owner__username')


@admin.register(VehicleVerification)
class VehicleVerificationAdmin(ReviewAdminMixin, admin.ModelAdmin):
    review_service = services

    list_display = ('vehicle', 'owner', 'status_badge', 'inspection_expiry', 'submitted_at')
    list_filter = ('status',)
    search_fields = ('vehicle__registration_number', 'owner__username')
    readonly_fields = ('status_badge', 'documents', 'submitted_at', 'reviewed_at',
                       'reviewed_by', 'updated_at')
    fieldsets = (
        ('Request', {'fields': ('vehicle', 'owner', 'inspection_expiry', 'insurance_expiry', 'documents')}),
        ('Review', {'fields': ('status', 'status_badge', 'rejection_reason',
                               'submitted_at', 'reviewed_at', 'reviewed_by', 'updated_at')}),
    )
