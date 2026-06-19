from rest_framework import serializers

from vehicles.models import Vehicle, VehicleVerification


class VehicleVerificationSubmitSerializer(serializers.Serializer):
    registration_number = serializers.CharField(max_length=50)
    vehicle_type = serializers.CharField(max_length=50)
    brand = serializers.CharField(max_length=100)
    model = serializers.CharField(max_length=100)
    year = serializers.IntegerField(min_value=1900, max_value=2100)
    registration_doc = serializers.FileField()
    proof_of_ownership = serializers.FileField()
    inspection_certificate = serializers.FileField(required=False)
    inspection_expiry = serializers.DateField(required=False)
    insurance = serializers.FileField(required=False)
    insurance_expiry = serializers.DateField(required=False)

    def vehicle_data(self):
        return {
            'registration_number': self.validated_data['registration_number'],
            'vehicle_type': self.validated_data['vehicle_type'],
            'brand': self.validated_data['brand'],
            'model': self.validated_data['model'],
            'year': self.validated_data['year'],
        }


class VehicleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vehicle
        fields = ['id', 'registration_number', 'vehicle_type', 'brand', 'model', 'year', 'is_verified']


class VehicleVerificationSerializer(serializers.ModelSerializer):
    vehicle = VehicleSerializer(read_only=True)
    inspection_expired = serializers.BooleanField(read_only=True)
    is_road_eligible = serializers.BooleanField(read_only=True)

    class Meta:
        model = VehicleVerification
        fields = [
            'id', 'vehicle', 'status', 'inspection_expiry', 'insurance_expiry',
            'inspection_expired', 'is_road_eligible', 'rejection_reason',
            'submitted_at', 'reviewed_at', 'updated_at',
        ]
        read_only_fields = fields
