"""
Route Intelligence models.

PlannedRoute  — the reference polyline for deviation detection (Story 1).
RouteDeviation — every anomaly detected against the planned route (Stories 3-4).
UnexpectedStop — prolonged stops detected during a journey (Story 5).
JourneyRisk    — live risk score + level for a journey (Story 8).
JourneyWarning — human-readable safety warnings sent to passengers (Story 9).
"""
import uuid

from django.db import models


class PlannedRoute(models.Model):
    """Expected route captured at journey start (Story 1)."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        DEVIATED = 'DEVIATED', 'Deviated'
        COMPLETED = 'COMPLETED', 'Completed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.OneToOneField(
        'journeys.Journey', on_delete=models.CASCADE, related_name='planned_route',
    )
    # Ordered list of {"lat": float, "lng": float} points.
    waypoints = models.JSONField(default=list, blank=True)
    expected_duration_s = models.IntegerField(null=True, blank=True)
    expected_distance_m = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'PlannedRoute({self.journey_id}, {self.status})'


class RouteDeviation(models.Model):
    """A detected deviation from the planned route (Stories 3-4)."""

    class DeviationType(models.TextChoices):
        ROUTE_DEVIATION = 'ROUTE_DEVIATION', 'Route Deviation'
        WRONG_DIRECTION = 'WRONG_DIRECTION', 'Wrong Direction'
        UNAUTHORIZED_CHANGE = 'UNAUTHORIZED_CHANGE', 'Unauthorized Route Change'
        EXCESSIVE_DETOUR = 'EXCESSIVE_DETOUR', 'Excessive Detour'

    class Severity(models.TextChoices):
        LOW = 'LOW', 'Low'
        MEDIUM = 'MEDIUM', 'Medium'
        HIGH = 'HIGH', 'High'
        CRITICAL = 'CRITICAL', 'Critical'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.ForeignKey(
        'journeys.Journey', on_delete=models.CASCADE, related_name='deviations',
    )
    deviation_type = models.CharField(max_length=24, choices=DeviationType.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MEDIUM)
    latitude = models.FloatField()
    longitude = models.FloatField()
    # For ROUTE_DEVIATION: metres off the planned route.
    distance_from_route_m = models.FloatField(null=True, blank=True)
    # For WRONG_DIRECTION: degrees off the destination bearing.
    heading_error_deg = models.FloatField(null=True, blank=True)
    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [models.Index(fields=['journey', '-timestamp'])]

    def __str__(self):
        return f'RouteDeviation({self.journey_id}, {self.deviation_type}, {self.severity})'


class UnexpectedStop(models.Model):
    """A prolonged stop detected during an active journey (Story 5)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.ForeignKey(
        'journeys.Journey', on_delete=models.CASCADE, related_name='unexpected_stops',
    )
    latitude = models.FloatField()
    longitude = models.FloatField()
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    # Computed duration in seconds (None while stop is ongoing).
    duration_s = models.IntegerField(null=True, blank=True)
    # Flag set by dangerous-area check (Story 6).
    is_unsafe_area = models.BooleanField(default=False)
    area_safety_score = models.FloatField(null=True, blank=True)
    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [models.Index(fields=['journey', '-started_at'])]

    def __str__(self):
        return f'UnexpectedStop({self.journey_id}, {self.started_at})'


class JourneyRisk(models.Model):
    """Live risk score for a journey, continuously updated (Story 8)."""

    class Level(models.TextChoices):
        LOW = 'LOW', 'Low'
        MEDIUM = 'MEDIUM', 'Medium'
        HIGH = 'HIGH', 'High'
        CRITICAL = 'CRITICAL', 'Critical'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.OneToOneField(
        'journeys.Journey', on_delete=models.CASCADE, related_name='risk',
    )
    # 0 = fully safe, 100 = maximum risk.
    score = models.FloatField(default=0.0)
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.LOW)
    # Breakdown: {"route_deviation": 20, "wrong_direction": 0, ...}
    factors = models.JSONField(default=dict, blank=True)
    # Whether iSafePass incident has been created for this journey.
    incident_created = models.BooleanField(default=False)
    incident_id = models.CharField(max_length=256, blank=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_updated']

    def __str__(self):
        return f'JourneyRisk({self.journey_id}, {self.score:.1f}, {self.level})'


class JourneyWarning(models.Model):
    """A human-readable safety warning raised during a journey (Story 9)."""

    class WarningType(models.TextChoices):
        ROUTE_DEVIATION = 'ROUTE_DEVIATION', 'Route Deviation'
        WRONG_DIRECTION = 'WRONG_DIRECTION', 'Wrong Direction'
        UNEXPECTED_STOP = 'UNEXPECTED_STOP', 'Unexpected Stop'
        DANGEROUS_AREA = 'DANGEROUS_AREA', 'Dangerous Area'
        HIGH_RISK = 'HIGH_RISK', 'High Risk Score'
        INCIDENT_RECOMMENDED = 'INCIDENT_RECOMMENDED', 'Incident Recommended'
        INCIDENT_CREATED = 'INCIDENT_CREATED', 'Incident Created in iSafePass'

    class Severity(models.TextChoices):
        INFO = 'INFO', 'Info'
        WARNING = 'WARNING', 'Warning'
        DANGER = 'DANGER', 'Danger'
        CRITICAL = 'CRITICAL', 'Critical'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.ForeignKey(
        'journeys.Journey', on_delete=models.CASCADE, related_name='warnings',
    )
    warning_type = models.CharField(max_length=24, choices=WarningType.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.WARNING)
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['journey', '-created_at'])]

    def __str__(self):
        return f'JourneyWarning({self.journey_id}, {self.warning_type}, {self.severity})'
