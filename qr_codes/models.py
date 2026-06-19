"""Persistent QR code records with revocation and scan audit trail.

Every verified driver (participant) and vehicle (asset) gets a QRCode row whose
signed token encodes this row's UUID.  The verify endpoint looks up that row to
check revocation status before trusting the token — closing the gap left by the
original stateless signed tokens (which could not be revoked).

QRScan logs every verification attempt (valid or not) for Stories 10 and 12.
"""
import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class QRCode(models.Model):
    """One active QR per verified entity (driver or vehicle)."""

    class EntityType(models.TextChoices):
        PARTICIPANT = 'PARTICIPANT', 'Participant'
        ASSET = 'ASSET', 'Asset'

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        REVOKED = 'REVOKED', 'Revoked'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    entity_type = models.CharField(max_length=16, choices=EntityType.choices)

    # Generic relation to Driver (participant) or Vehicle (asset).
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64)
    content_object = GenericForeignKey('content_type', 'object_id')

    # The signed v2 token that is actually encoded in the QR PNG.
    token = models.CharField(max_length=1024, unique=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    # Increments on every regeneration so history is preserved.
    generation = models.PositiveIntegerField(default=1)

    generated_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='revoked_qr_codes',
    )
    revoke_reason = models.TextField(blank=True)

    class Meta:
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['content_type', 'object_id', 'status']),
            models.Index(fields=['entity_type', 'status']),
        ]

    def __str__(self):
        return f'QRCode({self.entity_type}, gen={self.generation}, {self.status})'


class QRScan(models.Model):
    """Audit log for every QR verification attempt (Story 10 + 12)."""

    class Result(models.TextChoices):
        VALID = 'VALID', 'Valid'
        INVALID_TOKEN = 'INVALID_TOKEN', 'Invalid Token'
        REVOKED = 'REVOKED', 'Revoked'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        INELIGIBLE = 'INELIGIBLE', 'Ineligible'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    qr_code = models.ForeignKey(
        QRCode, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='scans',
    )
    scanned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='qr_scans',
    )
    token_tried = models.CharField(max_length=1024)
    result = models.CharField(max_length=16, choices=Result.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    scanned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-scanned_at']
        indexes = [
            models.Index(fields=['qr_code', '-scanned_at']),
            models.Index(fields=['scanned_by', '-scanned_at']),
            models.Index(fields=['result', '-scanned_at']),
        ]

    def __str__(self):
        return f'QRScan({self.result}, {self.scanned_at})'
