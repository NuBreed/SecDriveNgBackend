from rest_framework import serializers

from operators.models import (
    Branch, FleetAsset, FleetParticipant, FleetSafetyScore,
    OperatorMembership, OperatorVerification, ParticipantAssetAssignment,
    TransportOperator,
)


# ── KYC serializers (unchanged) ───────────────────────────────────────────────

class OperatorVerificationSubmitSerializer(serializers.Serializer):
    organization_name = serializers.CharField(max_length=255)
    cac_number = serializers.CharField(max_length=100)
    contact_info = serializers.CharField(max_length=255, required=False, allow_blank=True)
    certification_expiry = serializers.DateField(required=False)
    cac_certificate = serializers.FileField()
    proof_of_address = serializers.FileField()
    representative_id = serializers.FileField()


class OperatorVerificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = OperatorVerification
        fields = [
            'id', 'organization_name', 'cac_number', 'contact_info',
            'certification_expiry', 'status', 'is_verified', 'rejection_reason',
            'submitted_at', 'reviewed_at', 'updated_at',
        ]
        read_only_fields = fields


# ── Fleet Management serializers (Epic 8) ─────────────────────────────────────

class TransportOperatorRegisterSerializer(serializers.Serializer):
    organization_name = serializers.CharField(max_length=255)
    registration_number = serializers.CharField(max_length=100)
    business_type = serializers.ChoiceField(choices=TransportOperator.BusinessType.choices)
    contact_phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True)
    contact_address = serializers.CharField(required=False, allow_blank=True)


class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = ['id', 'name', 'branch_type', 'parent', 'address', 'phone', 'is_active', 'created_at']
        read_only_fields = ['id', 'created_at']


class OperatorMembershipSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = OperatorMembership
        fields = ['id', 'user', 'user_email', 'user_name', 'branch', 'role', 'is_active', 'joined_at']
        read_only_fields = ['id', 'joined_at']

    def get_user_name(self, obj) -> str:
        return obj.user.get_full_name()


class TransportOperatorSerializer(serializers.ModelSerializer):
    owner_email = serializers.EmailField(source='owner.email', read_only=True)
    branch_count = serializers.SerializerMethodField()
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = TransportOperator
        fields = [
            'id', 'organization_name', 'registration_number', 'business_type',
            'contact_phone', 'contact_email', 'contact_address',
            'fleet_safety_score', 'is_active',
            'owner_email', 'branch_count', 'member_count',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_branch_count(self, obj) -> int:
        return obj.branches.filter(is_active=True).count()

    def get_member_count(self, obj) -> int:
        return obj.memberships.filter(is_active=True).count()


class FleetParticipantSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    user_name = serializers.SerializerMethodField()
    driver_verification_status = serializers.SerializerMethodField()

    class Meta:
        model = FleetParticipant
        fields = [
            'id', 'user', 'user_email', 'user_name',
            'participant_type', 'status', 'suspension_reason',
            'branch', 'driver_verification_status',
            'added_at', 'updated_at',
        ]
        read_only_fields = fields

    def get_user_name(self, obj) -> str:
        return obj.user.get_full_name()

    def get_driver_verification_status(self, obj) -> str:
        if obj.driver:
            return obj.driver.verification_status
        return ''


class AssignParticipantSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    participant_type = serializers.ChoiceField(choices=FleetParticipant.ParticipantType.choices)
    branch_id = serializers.UUIDField(required=False, allow_null=True)


class FleetAssetSerializer(serializers.ModelSerializer):
    vehicle_registration = serializers.CharField(source='vehicle.registration_number', read_only=True)
    vehicle_brand = serializers.CharField(source='vehicle.brand', read_only=True)
    vehicle_model = serializers.CharField(source='vehicle.model', read_only=True)
    is_verified = serializers.BooleanField(source='vehicle.is_verified', read_only=True)

    class Meta:
        model = FleetAsset
        fields = [
            'id', 'vehicle', 'vehicle_registration', 'vehicle_brand', 'vehicle_model',
            'is_verified', 'status', 'branch', 'added_at', 'updated_at',
        ]
        read_only_fields = fields


class AddAssetSerializer(serializers.Serializer):
    vehicle_id = serializers.IntegerField()
    branch_id = serializers.UUIDField(required=False, allow_null=True)


class ParticipantAssetAssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ParticipantAssetAssignment
        fields = ['id', 'participant', 'asset', 'assigned_at', 'unassigned_at', 'is_active']
        read_only_fields = fields


class AssignToAssetSerializer(serializers.Serializer):
    participant_id = serializers.UUIDField()
    asset_id = serializers.UUIDField()


class FleetSafetyScoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = FleetSafetyScore
        fields = [
            'score', 'level',
            'incident_factor', 'deviation_factor',
            'compliance_factor', 'performance_factor',
            'computed_at',
        ]
        read_only_fields = fields
