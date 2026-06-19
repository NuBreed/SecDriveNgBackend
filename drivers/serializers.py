from rest_framework import serializers

from drivers.models import DriverVerification


class DriverVerificationSubmitSerializer(serializers.Serializer):
    license_number = serializers.CharField(max_length=100)
    license_expiry = serializers.DateField()
    national_id = serializers.FileField()
    driver_license = serializers.FileField()
    passport_photo = serializers.ImageField(required=False)
    selfie = serializers.ImageField(required=False)


class DriverVerificationSerializer(serializers.ModelSerializer):
    license_expired = serializers.BooleanField(read_only=True)
    can_operate = serializers.BooleanField(read_only=True)

    class Meta:
        model = DriverVerification
        fields = [
            'id', 'license_number', 'license_expiry', 'license_expired',
            'status', 'background_review_passed', 'can_operate',
            'rejection_reason', 'submitted_at', 'reviewed_at', 'updated_at',
        ]
        read_only_fields = fields
