from rest_framework import serializers

from operators.models import OperatorVerification


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
