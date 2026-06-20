from rest_framework import serializers

from route_intelligence.models import (
    JourneyRisk, JourneyWarning, PlannedRoute, RouteDeviation, UnexpectedStop,
)


class PlannedRouteSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlannedRoute
        fields = ['id', 'journey', 'waypoints', 'expected_duration_s',
                  'expected_distance_m', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'journey', 'status', 'created_at', 'updated_at']


class RouteDeviationSerializer(serializers.ModelSerializer):
    class Meta:
        model = RouteDeviation
        fields = ['id', 'deviation_type', 'severity', 'latitude', 'longitude',
                  'distance_from_route_m', 'heading_error_deg',
                  'is_resolved', 'resolved_at', 'metadata', 'timestamp']
        read_only_fields = fields


class UnexpectedStopSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnexpectedStop
        fields = ['id', 'latitude', 'longitude', 'started_at', 'ended_at',
                  'duration_s', 'is_unsafe_area', 'area_safety_score',
                  'is_resolved', 'resolved_at']
        read_only_fields = fields


class JourneyRiskSerializer(serializers.ModelSerializer):
    class Meta:
        model = JourneyRisk
        fields = ['id', 'journey', 'score', 'level', 'factors',
                  'incident_created', 'incident_id', 'last_updated']
        read_only_fields = fields


class JourneyWarningSerializer(serializers.ModelSerializer):
    class Meta:
        model = JourneyWarning
        fields = ['id', 'warning_type', 'severity', 'title', 'message',
                  'is_resolved', 'resolved_at', 'metadata', 'created_at']
        read_only_fields = fields


class RouteAnalysisSerializer(serializers.Serializer):
    journey_id = serializers.UUIDField()
    planned_route = PlannedRouteSerializer(allow_null=True)
    deviations = RouteDeviationSerializer(many=True)
    unexpected_stops = UnexpectedStopSerializer(many=True)
    risk = JourneyRiskSerializer(allow_null=True)
    warnings = JourneyWarningSerializer(many=True)


class EscalateSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=512, required=False, allow_blank=True, default='')


# ── Route Safety Check (pre-ride) ─────────────────────────────────────────────

class SafeAlternativeSerializer(serializers.Serializer):
    name         = serializers.CharField()
    description  = serializers.CharField()
    safety_level = serializers.CharField()
    safety_score = serializers.IntegerField()


class RiskItemSerializer(serializers.Serializer):
    label = serializers.CharField()
    count = serializers.IntegerField()


class RouteCheckRequestSerializer(serializers.Serializer):
    place_id    = serializers.CharField()
    destination = serializers.CharField()


class RouteCheckResponseSerializer(serializers.Serializer):
    destination      = serializers.CharField()
    safety_level     = serializers.CharField()
    safety_score     = serializers.IntegerField()
    summary          = serializers.CharField()
    risks            = RiskItemSerializer(many=True)
    recommendations  = serializers.ListField(child=serializers.CharField())
    alternatives     = SafeAlternativeSerializer(many=True)
