"""
Accident Detection & Emergency Escalation models (Epic 7).

AccidentEvent     — a detected impact / rollover / sudden-stop / possible-accident.
SOSRequest        — manual SOS or panic-button activation.
EmergencyEscalation — an escalation sent (or attempted) to iSafePass.
DeliveryLog       — per-attempt delivery record for health monitoring (Story 12).
"""
import uuid

from django.conf import settings
from django.db import models


class AccidentEvent(models.Model):
    """A detected or reported accident / emergency event (Stories 1-3, 6-7)."""

    class EventType(models.TextChoices):
        IMPACT = 'IMPACT', 'Impact Detected'
        ROLLOVER = 'ROLLOVER', 'Rollover Detected'
        SUDDEN_STOP = 'SUDDEN_STOP', 'Sudden Stop Detected'
        POSSIBLE_ACCIDENT = 'POSSIBLE_ACCIDENT', 'Possible Accident'

    class Severity(models.TextChoices):
        LOW = 'LOW', 'Low'
        MEDIUM = 'MEDIUM', 'Medium'
        HIGH = 'HIGH', 'High'
        CRITICAL = 'CRITICAL', 'Critical'

    class ConfirmationStatus(models.TextChoices):
        PENDING = 'PENDING', 'Awaiting User Response'
        SAFE = 'SAFE', 'User Confirmed Safe'
        NEEDS_HELP = 'NEEDS_HELP', 'User Requested Help'
        TIMED_OUT = 'TIMED_OUT', 'No Response — Auto-Escalated'
        ESCALATED = 'ESCALATED', 'Escalated to iSafePass'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.ForeignKey(
        'journeys.Journey', on_delete=models.CASCADE, related_name='accident_events',
    )
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    severity = models.CharField(max_length=10, choices=Severity.choices, default=Severity.MEDIUM)
    confirmation_status = models.CharField(
        max_length=12, choices=ConfirmationStatus.choices, default=ConfirmationStatus.PENDING,
    )
    # Location at time of detection.
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    # Sensor readings that triggered the event.
    acceleration_magnitude = models.FloatField(null=True, blank=True)  # m/s²
    speed_before = models.FloatField(null=True, blank=True)            # m/s
    speed_after = models.FloatField(null=True, blank=True)             # m/s
    tilt_angle = models.FloatField(null=True, blank=True)              # degrees
    rotation_rate = models.FloatField(null=True, blank=True)           # deg/s
    raw_sensor = models.JSONField(default=dict, blank=True)
    # Timestamps.
    detected_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    # Task ID for the auto-escalation countdown (Celery ETA task).
    countdown_task_id = models.CharField(max_length=256, blank=True)

    class Meta:
        ordering = ['-detected_at']
        indexes = [models.Index(fields=['journey', '-detected_at'])]

    def __str__(self):
        return f'AccidentEvent({self.journey_id}, {self.event_type}, {self.severity})'


class SOSRequest(models.Model):
    """A manual SOS or panic-button activation (Stories 4-5)."""

    class SOSType(models.TextChoices):
        PASSENGER_SOS = 'PASSENGER_SOS', 'Passenger SOS'
        DRIVER_PANIC = 'DRIVER_PANIC', 'Driver/Rider Panic Button'

    class Status(models.TextChoices):
        TRIGGERED = 'TRIGGERED', 'Triggered'
        DELIVERED = 'DELIVERED', 'Delivered to iSafePass'
        FAILED = 'FAILED', 'Delivery Failed'
        RETRYING = 'RETRYING', 'Retrying Delivery'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.ForeignKey(
        'journeys.Journey', on_delete=models.CASCADE, related_name='sos_requests',
    )
    triggered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='sos_triggers',
    )
    sos_type = models.CharField(max_length=16, choices=SOSType.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.TRIGGERED)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    message = models.TextField(blank=True)
    # iSafePass response.
    isafepass_sos_id = models.CharField(max_length=256, blank=True)
    response_data = models.JSONField(default=dict, blank=True)
    triggered_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['-triggered_at']
        indexes = [models.Index(fields=['journey', '-triggered_at'])]

    def __str__(self):
        return f'SOSRequest({self.journey_id}, {self.sos_type}, {self.status})'


class EmergencyEscalation(models.Model):
    """An escalation to iSafePass — incident creation or SOS forwarding (Stories 8, 12)."""

    class EscalationType(models.TextChoices):
        SOS = 'SOS', 'SOS Request'
        ACCIDENT_INCIDENT = 'ACCIDENT_INCIDENT', 'Accident Incident'
        PANIC = 'PANIC', 'Panic Button'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        DELIVERED = 'DELIVERED', 'Delivered'
        FAILED = 'FAILED', 'Failed'
        RETRYING = 'RETRYING', 'Retrying'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.ForeignKey(
        'journeys.Journey', on_delete=models.CASCADE, related_name='emergency_escalations',
    )
    accident_event = models.ForeignKey(
        AccidentEvent, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='escalations',
    )
    sos_request = models.ForeignKey(
        SOSRequest, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='escalations',
    )
    escalation_type = models.CharField(max_length=20, choices=EscalationType.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    # iSafePass incident / SOS identifiers.
    isafepass_incident_id = models.CharField(max_length=256, blank=True)
    isafepass_sos_id = models.CharField(max_length=256, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    response_data = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)
    max_retries = models.PositiveSmallIntegerField(default=3)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['journey', '-created_at']),
            models.Index(fields=['status', 'next_retry_at']),
        ]

    def __str__(self):
        return f'EmergencyEscalation({self.journey_id}, {self.escalation_type}, {self.status})'


class DeliveryLog(models.Model):
    """Immutable per-attempt delivery record for health monitoring (Story 12)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    escalation = models.ForeignKey(
        EmergencyEscalation, on_delete=models.CASCADE, related_name='delivery_logs',
    )
    attempt_number = models.PositiveSmallIntegerField(default=1)
    success = models.BooleanField(default=False)
    http_status = models.IntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True)
    error = models.TextField(blank=True)
    duration_ms = models.IntegerField(null=True, blank=True)
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-attempted_at']

    def __str__(self):
        ok = 'OK' if self.success else 'FAIL'
        return f'DeliveryLog({self.escalation_id}, attempt={self.attempt_number}, {ok})'
