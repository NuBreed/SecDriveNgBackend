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
            'duration_seconds', 'last_location',
        ]
        read_only_fields = [
            'id', 'passenger', 'driver', 'vehicle',
            'participant_qr', 'asset_qr', 'status',
            'created_at', 'started_at', 'paused_at', 'completed_at', 'cancelled_at',
            'duration_seconds', 'last_location',
        ]


# ── Request serializers ────────────────────────────────────────────────────────

class JourneyCreateSerializer(serializers.Serializer):
    participant_token = serializers.CharField(
        help_text='Signed QR token for the transport participant (driver).',
    )
    asset_token = serializers.CharField(
        help_text='Signed QR token for the transport asset (vehicle).',
    )


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
