import uuid

from django.conf import settings
from django.db import models


class Notification(models.Model):
    """Lightweight in-app notification (KYC status updates, reminders)."""

    class Type(models.TextChoices):
        KYC_UPDATE = 'KYC_UPDATE'
        REVERIFICATION = 'REVERIFICATION'
        RIDE = 'RIDE'
        SOS = 'SOS'
        VERIFICATION = 'VERIFICATION'
        NEWS = 'NEWS'
        GENERAL = 'GENERAL'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications',
    )
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.GENERAL)
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'read'])]

    def __str__(self):
        return f'Notification({self.user}, {self.title})'


class NotificationPreference(models.Model):
    """Per-user notification channel preferences."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_prefs',
    )
    ride_alerts = models.BooleanField(default=True)
    sos_alerts = models.BooleanField(default=True)
    verification_alerts = models.BooleanField(default=True)
    news_alerts = models.BooleanField(default=False)
    # Device push token for FCM / APNs (updated whenever app launches).
    push_token = models.CharField(max_length=512, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'NotificationPreference({self.user})'
