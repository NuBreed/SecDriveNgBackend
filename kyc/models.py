import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class VerificationStatus(models.TextChoices):
    """Shared status workflow for every verification request type."""
    NOT_SUBMITTED = 'NOT_SUBMITTED', 'Not Submitted'
    PENDING = 'PENDING', 'Pending Review'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected'
    MORE_INFO = 'MORE_INFO', 'More Info Required'
    SUSPENDED = 'SUSPENDED', 'Suspended'
    ESCALATED = 'ESCALATED', 'Escalated'


class IdentityVerification(models.Model):
    """A user's identity (Level 2) KYC request."""

    class IDType(models.TextChoices):
        NATIONAL_ID = 'NATIONAL_ID', 'National ID'
        VOTER_CARD = 'VOTER_CARD', 'Voter Card'
        PASSPORT = 'PASSPORT', 'Passport'
        DRIVER_LICENSE = 'DRIVER_LICENSE', 'Driver License'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='identity_verification',
    )
    primary_id_type = models.CharField(max_length=20, choices=IDType.choices)
    status = models.CharField(
        max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.PENDING,
    )
    rejection_reason = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='identity_reviews',
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'IdentityVerification({self.user}, {self.status})'


class ReviewEvent(models.Model):
    """Audit trail of admin review decisions across all verification types."""

    class Action(models.TextChoices):
        SUBMITTED = 'SUBMITTED'
        APPROVED = 'APPROVED'
        REJECTED = 'REJECTED'
        MORE_INFO = 'MORE_INFO'
        SUSPENDED = 'SUSPENDED'
        ESCALATED = 'ESCALATED'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='review_events',
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.CharField(max_length=64)
    content_object = GenericForeignKey('content_type', 'object_id')
    action = models.CharField(max_length=16, choices=Action.choices)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['content_type', 'object_id'])]

    def __str__(self):
        return f'ReviewEvent({self.action} by {self.actor})'
