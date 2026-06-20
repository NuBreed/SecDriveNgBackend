"""Models for external integration state tracking."""
import uuid

from django.db import models


class JourneySubscription(models.Model):
    """Records the iSafePass safety-monitoring subscription for a journey (Story 7)."""

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        ACTIVE = 'ACTIVE', 'Active'
        CLOSED = 'CLOSED', 'Closed'
        FAILED = 'FAILED', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    journey = models.OneToOneField(
        'journeys.Journey', on_delete=models.CASCADE,
        related_name='isafepass_subscription',
    )
    # ID returned by iSafePass after a successful subscribe call.
    isafepass_subscription_id = models.CharField(max_length=256, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    response_data = models.JSONField(default=dict, blank=True)
    subscribed_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-subscribed_at']

    def __str__(self):
        return f'JourneySubscription({self.journey_id}, {self.status})'
