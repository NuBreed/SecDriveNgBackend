from rest_framework import serializers

from journeys.models import Journey, JourneyEvent, JourneyLocation


class JourneyLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = JourneyLocation
        fields = [
            'id', 'latitude', 'longitude', 'speed', 'heading',
            'accuracy', 'altitude', 'client_timestamp', 'timestamp',
        ]
        read_only_fields = ['id', 'timestamp']


class JourneyEventSerializer(serializers.ModelSerializer):
    actor_username = serializers.SerializerMethodField()

    class Meta:
        model = JourneyEvent
        fields = ['id', 'event_type', 'actor', 'actor_username', 'metadata', 'timestamp']
        read_only_fields = fields

    def get_actor_username(self, obj) -> str | None:
        return obj.actor.username if obj.actor else None


class JourneySerializer(serializers.ModelSerializer):
    duration_seconds = serializers.IntegerField(read_only=True, allow_null=True)
    last_location = JourneyLocationSerializer(read_only=True)

    class Meta:
        model = Journey
        fields = [
            'id', 'passenger', 'driver', 'vehicle',
            'participant_qr', 'asset_qr',
            'status',
            'origin_lat', 'origin_lng', 'origin_address',
            'destination_lat', 'destination_lng', 'destination_address',
            'estimated_distance_m', 'estimated_duration_s',
            'created_at', 'started_at', 'paused_at', 'completed_at', 'cancelled_at',
            'pause_reason', 'cancellation_reason',
            'group_size',
            'duration_seconds', 'last_location',
        ]
        read_only_fields = [
            'id', 'passenger', 'driver', 'vehicle',
            'participant_qr', 'asset_qr', 'status',
            'created_at', 'started_at', 'paused_at', 'completed_at', 'cancelled_at',
            'duration_seconds', 'last_location',
        ]


class DriverJourneySerializer(JourneySerializer):
    """JourneySerializer extended with passenger contact details for driver views."""
    passenger_name = serializers.SerializerMethodField()
    passenger_phone = serializers.SerializerMethodField()
    avg_speed_kmh = serializers.SerializerMethodField()
    max_speed_kmh = serializers.SerializerMethodField()

    class Meta(JourneySerializer.Meta):
        fields = JourneySerializer.Meta.fields + [
            'passenger_name', 'passenger_phone',
            'avg_speed_kmh', 'max_speed_kmh',
        ]

    def get_passenger_name(self, obj):
        u = obj.passenger
        return f'{u.first_name} {u.last_name}'.strip() or u.email

    def get_passenger_phone(self, obj):
        return getattr(obj.passenger, 'phone_number', '') or ''

    def _speed_pings(self, obj):
        return [
            loc.speed for loc in obj.locations.all()
            if loc.speed is not None and loc.speed > 0
        ]

    def get_avg_speed_kmh(self, obj):
        pings = self._speed_pings(obj)
        if not pings:
            return None
        return round(sum(pings) / len(pings) * 3.6, 1)

    def get_max_speed_kmh(self, obj):
        pings = self._speed_pings(obj)
        return round(max(pings) * 3.6, 1) if pings else None


# ── Request serializers ────────────────────────────────────────────────────────

class JourneyCreateSerializer(serializers.Serializer):
    participant_token = serializers.CharField(
        help_text='Signed QR token for the transport participant (driver).',
    )
    asset_token = serializers.CharField(
        required=False, allow_blank=True, default='',
        help_text='Signed QR token for the transport asset (vehicle). '
                  'If omitted the driver\'s verified vehicle is used automatically.',
    )
    group_size = serializers.IntegerField(
        required=False, default=1, min_value=1, max_value=20,
        help_text='Total number of people travelling (passenger + companions).',
    )
    destination_lat     = serializers.FloatField(required=False, allow_null=True)
    destination_lng     = serializers.FloatField(required=False, allow_null=True)
    destination_address = serializers.CharField(required=False, allow_blank=True, default='')
    origin_lat          = serializers.FloatField(required=False, allow_null=True)
    origin_lng          = serializers.FloatField(required=False, allow_null=True)
    origin_address      = serializers.CharField(required=False, allow_blank=True, default='')


class DestinationSerializer(serializers.Serializer):
    origin_lat = serializers.FloatField()
    origin_lng = serializers.FloatField()
    origin_address = serializers.CharField(required=False, allow_blank=True, default='')
    destination_lat = serializers.FloatField()
    destination_lng = serializers.FloatField()
    destination_address = serializers.CharField(required=False, allow_blank=True, default='')
    estimated_distance_m = serializers.FloatField(required=False, allow_null=True)
    estimated_duration_s = serializers.IntegerField(required=False, allow_null=True)


class PauseSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default='')


class CancelSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default='')


class LocationUpdateSerializer(serializers.Serializer):
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()
    speed = serializers.FloatField(required=False, allow_null=True)
    heading = serializers.FloatField(required=False, allow_null=True)
    accuracy = serializers.FloatField(required=False, allow_null=True)
    altitude = serializers.FloatField(required=False, allow_null=True)
    client_timestamp = serializers.DateTimeField(required=False, allow_null=True)
