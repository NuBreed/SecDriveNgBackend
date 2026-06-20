from django.contrib import admin

from common.admin_mixins import ReviewAdminMixin
from operators import services
from operators.models import (
    Branch, FleetAsset, FleetParticipant, FleetSafetyScore,
    OperatorMembership, OperatorVerification, ParticipantAssetAssignment,
    TransportOperator,
)


# ── KYC admin ─────────────────────────────────────────────────────────────────

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


# ── Fleet Management admin ────────────────────────────────────────────────────

class BranchInline(admin.TabularInline):
    model = Branch
    extra = 0
    fields = ('name', 'branch_type', 'parent', 'is_active')
    show_change_link = True


class MembershipInline(admin.TabularInline):
    model = OperatorMembership
    extra = 0
    fields = ('user', 'role', 'branch', 'is_active')


@admin.register(TransportOperator)
class TransportOperatorAdmin(admin.ModelAdmin):
    list_display = (
        'organization_name', 'business_type', 'owner',
        'fleet_safety_score', 'is_active', 'created_at',
    )
    list_filter = ('business_type', 'is_active')
    search_fields = ('organization_name', 'registration_number', 'owner__email')
    readonly_fields = ('id', 'fleet_safety_score', 'created_at', 'updated_at')
    inlines = [BranchInline, MembershipInline]
    ordering = ('-created_at',)


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'operator', 'branch_type', 'parent', 'is_active')
    list_filter = ('branch_type', 'is_active')
    search_fields = ('name', 'operator__organization_name')


@admin.register(OperatorMembership)
class OperatorMembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'operator', 'role', 'branch', 'is_active', 'joined_at')
    list_filter = ('role', 'is_active')
    search_fields = ('user__email', 'operator__organization_name')


class AssetAssignmentInline(admin.TabularInline):
    model = ParticipantAssetAssignment
    fk_name = 'participant'
    extra = 0
    fields = ('asset', 'is_active', 'assigned_at', 'unassigned_at')
    readonly_fields = ('assigned_at', 'unassigned_at')


@admin.register(FleetParticipant)
class FleetParticipantAdmin(admin.ModelAdmin):
    list_display = ('user', 'operator', 'participant_type', 'status', 'added_at')
    list_filter = ('participant_type', 'status')
    search_fields = ('user__email', 'operator__organization_name')
    readonly_fields = ('id', 'added_at', 'updated_at')
    inlines = [AssetAssignmentInline]


class ParticipantAssignmentInline(admin.TabularInline):
    model = ParticipantAssetAssignment
    fk_name = 'asset'
    extra = 0
    fields = ('participant', 'is_active', 'assigned_at', 'unassigned_at')
    readonly_fields = ('assigned_at', 'unassigned_at')


@admin.register(FleetAsset)
class FleetAssetAdmin(admin.ModelAdmin):
    list_display = ('vehicle', 'operator', 'status', 'branch', 'added_at')
    list_filter = ('status',)
    search_fields = ('vehicle__registration_number', 'operator__organization_name')
    readonly_fields = ('id', 'added_at', 'updated_at')
    inlines = [ParticipantAssignmentInline]


@admin.register(ParticipantAssetAssignment)
class ParticipantAssetAssignmentAdmin(admin.ModelAdmin):
    list_display = ('participant', 'asset', 'is_active', 'assigned_at', 'unassigned_at')
    list_filter = ('is_active',)
    readonly_fields = ('id', 'assigned_at')


@admin.register(FleetSafetyScore)
class FleetSafetyScoreAdmin(admin.ModelAdmin):
    list_display = ('operator', 'score', 'level', 'computed_at')
    list_filter = ('level',)
    readonly_fields = ('id', 'score', 'level', 'incident_factor', 'deviation_factor',
                       'compliance_factor', 'performance_factor', 'computed_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
