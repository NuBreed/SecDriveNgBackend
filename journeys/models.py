"""Journey lifecycle models.

Lifecycle
---------
Created → Verified → Active → Paused → Active → Completed
                                ↓
                             Cancelled

Emergency path (from Active):
Active → Incident → Escalated → Resolved
"""
import uuid

from django.conf import settings
from django.db import models

from drivers.models import Driver
from vehicles.models import Vehicle


class Journey(models.Model):

    class Status(models.TextChoices):
        CREATED = 'CREATED', 'Created'
        VERIFIED = 'VERIFIED', 'Verified'
        ACTIVE = 'ACTIVE', 'Active'
        PAUSED = 'PAUSED', 'Paused'
        COMPLETED = 'COMPLETED', 'Completed'
        CANCELLED = 'CANCELLED', 'Cancelled'
        INCIDENT = 'INCIDENT', 'Incident'
        ESCALATED = 'ESCALATED', 'Escalated'
        RESOLVED = 'RESOLVED', 'Resolved'

    # Use UUID so clients can reference journeys without exposing sequential IDs.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    passenger = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='journeys_as_passenger',
    )
    driver = models.ForeignKey(
        Driver, on_delete=models.CASCADE, related_name='journeys',
    )
    vehicle = models.ForeignKey(
        Vehicle, on_delete=models.CASCADE, related_name='journeys',
    )

    # QR records used to verify the participant and asset.
    participant_qr = models.ForeignKey(
        'qr_codes.QRCode', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='participant_journeys',
    )
    asset_qr = models.ForeignKey(
        'qr_codes.QRCode', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='asset_journeys',
    )

    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.CREATED,
    )

    # Origin / destination
    origin_lat = models.FloatField(null=True, blank=True)
    origin_lng = models.FloatField(null=True, blank=True)
    origin_address = models.CharField(max_length=512, blank=True)
    destination_lat = models.FloatField(null=True, blank=True)
    destination_lng = models.FloatField(null=True, blank=True)
    destination_address = models.CharField(max_length=512, blank=True)

    # Estimates (set after destination is defined).
    estimated_distance_m = models.FloatField(null=True, blank=True)
    estimated_duration_s = models.IntegerField(null=True, blank=True)

    # Lifecycle timestamps.
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    paused_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    # Group size (passenger + children / companions).
    group_size = models.PositiveSmallIntegerField(default=1)

    # Cancellation / pause meta.
    pause_reason = models.CharField(max_length=256, blank=True)
    cancellation_reason = models.CharField(max_length=256, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['passenger', '-created_at']),
            models.Index(fields=['driver', '-created_at']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f'Journey({self.id}, {self.status})'

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    @property
    def is_terminal(self):
        return self.status in (self.Status.COMPLETED, self.Status.CANCELLED)

    @property
    def duration_seconds(self):
        if self.started_at is None:
            return None
        end = self.completed_at or self.cancelled_at
        if end:
            return int((end - self.started_at).total_seconds())
        from django.utils import timezone
        return int((timezone.now() - self.started_at).total_seconds())

    @property
    def last_location(self):
        return self.locations.order_by('-timestamp').first()


class JourneyLocation(models.Model):
    """GPS ping recorded during an active journey (Story 5 / Story 13)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.ForeignKey(Journey, on_delete=models.CASCADE, related_name='locations')
    latitude = models.FloatField()
    longitude = models.FloatField()
    accuracy = models.FloatField(null=True, blank=True)
    speed = models.FloatField(null=True, blank=True)       # m/s
    heading = models.FloatField(null=True, blank=True)     # degrees 0-360
    altitude = models.FloatField(null=True, blank=True)
    # Client-side UTC timestamp — allows dedup of buffered updates (Story 13).
    client_timestamp = models.DateTimeField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['journey', '-timestamp']),
        ]

    def __str__(self):
        return f'Location({self.journey_id}, {self.latitude},{self.longitude})'


class JourneyEvent(models.Model):
    """Immutable timeline entry for every lifecycle event (Stories 7 & 12)."""

    class EventType(models.TextChoices):
        CREATED = 'journey.created', 'Journey Created'
        STARTED = 'journey.started', 'Journey Started'
        PAUSED = 'journey.paused', 'Journey Paused'
        RESUMED = 'journey.resumed', 'Journey Resumed'
        COMPLETED = 'journey.completed', 'Journey Completed'
        CANCELLED = 'journey.cancelled', 'Journey Cancelled'
        DESTINATION_SET = 'destination.set', 'Destination Set'
        ROUTE_UPDATED = 'route.updated', 'Route Updated'
        ALERT = 'alert', 'Alert'
        PARTICIPANT_CONNECTED = 'participant.connected', 'Participant Connected'
        PARTICIPANT_DISCONNECTED = 'participant.disconnected', 'Participant Disconnected'
        PASSENGER_CONNECTED = 'passenger.connected', 'Passenger Connected'
        PASSENGER_DISCONNECTED = 'passenger.disconnected', 'Passenger Disconnected'
        LOCATION_UPDATED = 'location.updated', 'Location Updated'
        INCIDENT = 'incident', 'Incident'
        ESCALATED = 'escalated', 'Escalated'
        RESOLVED = 'resolved', 'Resolved'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.ForeignKey(Journey, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=32, choices=EventType.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='journey_events',
    )
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['journey', '-timestamp']),
            models.Index(fields=['event_type']),
        ]

    def __str__(self):
        return f'Event({self.event_type}, {self.journey_id})'


class JourneyShare(models.Model):
    """A record that a specific TrustedContact is monitoring this journey."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.ForeignKey(Journey, on_delete=models.CASCADE, related_name='shares')
    contact = models.ForeignKey(
        'safety.TrustedContact', on_delete=models.CASCADE, related_name='journey_shares',
    )
    # Granular privacy controls (Story 13).
    privacy = models.JSONField(
        default=dict,
        blank=True,
        help_text='e.g. {"show_location": true, "show_participant": true, "show_asset": true}',
    )
    active = models.BooleanField(default=True)
    shared_at = models.DateTimeField(auto_now_add=True)
    unshared_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-shared_at']
        unique_together = [('journey', 'contact')]

    def __str__(self):
        return f'JourneyShare({self.journey_id} → {self.contact_id})'

    @property
    def default_privacy(self):
        return {
            'show_location': True,
            'show_participant': True,
            'show_asset': True,
            'show_name': True,
        }

    def get_privacy(self):
        base = self.default_privacy
        base.update(self.privacy)
        return base


class JourneySensorData(models.Model):
    """Accelerometer + GPS sample posted by the passenger app for crash detection."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.ForeignKey(Journey, on_delete=models.CASCADE, related_name='sensor_data')
    acceleration_x = models.FloatField()
    acceleration_y = models.FloatField()
    acceleration_z = models.FloatField()
    acceleration_magnitude = models.FloatField()
    speed = models.FloatField(null=True, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [models.Index(fields=['journey', '-timestamp'])]

    def __str__(self):
        return f'SensorData({self.journey_id}, mag={self.acceleration_magnitude:.2f})'


class TrackingLink(models.Model):
    """Secure, shareable link that lets recipients view a live journey (Story 6)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.ForeignKey(Journey, on_delete=models.CASCADE, related_name='tracking_links')
    token = models.CharField(max_length=512, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='created_tracking_links',
    )
    active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'TrackingLink({self.journey_id})'

    @property
    def is_valid(self):
        from django.utils import timezone
        if not self.active:
            return False
        if self.expires_at and timezone.now() > self.expires_at:
            return False
        return True
