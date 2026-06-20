from rest_framework import serializers

from accident_detection.models import (
    AccidentEvent, DeliveryLog, EmergencyEscalation, SOSRequest,
)


class AccidentEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccidentEvent
        fields = [
            'id', 'journey', 'event_type', 'severity', 'confirmation_status',
            'latitude', 'longitude', 'acceleration_magnitude',
            'speed_before', 'speed_after', 'tilt_angle', 'rotation_rate',
            'detected_at', 'confirmed_at', 'escalated_at',
        ]
        read_only_fields = fields


class SOSRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = SOSRequest
        fields = [
            'id', 'journey', 'sos_type', 'status', 'latitude', 'longitude',
            'message', 'isafepass_sos_id', 'triggered_at', 'delivered_at', 'retry_count',
        ]
        read_only_fields = fields


class EmergencyEscalationSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmergencyEscalation
        fields = [
            'id', 'journey', 'escalation_type', 'status',
            'isafepass_incident_id', 'isafepass_sos_id',
            'error_message', 'retry_count', 'created_at', 'delivered_at',
        ]
        read_only_fields = fields


class DeliveryLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryLog
        fields = [
            'id', 'escalation', 'attempt_number', 'success',
            'http_status', 'error', 'duration_ms', 'attempted_at',
        ]
        read_only_fields = fields


class SensorDataSerializer(serializers.Serializer):
    acceleration_x = serializers.FloatField(required=False, allow_null=True)
    acceleration_y = serializers.FloatField(required=False, allow_null=True)
    acceleration_z = serializers.FloatField(required=False, allow_null=True)
    acceleration_magnitude = serializers.FloatField(required=False, allow_null=True)
    rotation_x = serializers.FloatField(required=False, allow_null=True)
    rotation_y = serializers.FloatField(required=False, allow_null=True)
    rotation_z = serializers.FloatField(required=False, allow_null=True)
    rotation_rate = serializers.FloatField(required=False, allow_null=True)
    tilt_angle = serializers.FloatField(required=False, allow_null=True)
    speed = serializers.FloatField(required=False, allow_null=True)
    lat = serializers.FloatField(required=False, allow_null=True)
    lng = serializers.FloatField(required=False, allow_null=True)


class SOSTriggerSerializer(serializers.Serializer):
    lat = serializers.FloatField(required=False, allow_null=True)
    lng = serializers.FloatField(required=False, allow_null=True)
    message = serializers.CharField(max_length=512, required=False, allow_blank=True, default='')


class AccidentConfirmSerializer(serializers.Serializer):
    event_id = serializers.UUIDField()
    response = serializers.ChoiceField(choices=['SAFE', 'NEEDS_HELP'])
