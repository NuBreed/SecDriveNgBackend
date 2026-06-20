from rest_framework import serializers

from drivers.models import Driver, DriverVerification


class DriverListSerializer(serializers.ModelSerializer):
    id             = serializers.UUIDField(source='user.id', read_only=True)
    full_name      = serializers.SerializerMethodField()
    phone          = serializers.CharField(source='user.phone_number', default='')
    state          = serializers.CharField(source='user.state', default='')
    photo_url      = serializers.SerializerMethodField()
    vehicle_type   = serializers.CharField(source='participant_type')
    is_verified    = serializers.SerializerMethodField()
    license_number = serializers.CharField()
    rating         = serializers.FloatField(source='trust_score')
    plate_number   = serializers.SerializerMethodField()
    operator_name  = serializers.SerializerMethodField()

    class Meta:
        model  = Driver
        fields = [
            'id', 'full_name', 'phone', 'state', 'photo_url',
            'vehicle_type', 'is_verified', 'license_number',
            'rating', 'plate_number', 'operator_name', 'trust_score',
            'verification_status', 'created_at',
        ]

    def get_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    def get_photo_url(self, obj):
        req = self.context.get('request')
        photo = getattr(obj.user, 'photo', None)
        if photo and req:
            return req.build_absolute_uri(photo.url)
        return None

    def get_is_verified(self, obj):
        ver = getattr(obj, 'verification', None)
        return bool(ver and ver.can_operate)

    def get_plate_number(self, obj):
        return getattr(obj.user, 'plate_number', '') or ''

    def get_operator_name(self, obj):
        op = getattr(obj.user, 'operator', None)
        return str(op) if op else ''


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
