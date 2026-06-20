"""Trusted contacts: family members, friends, and emergency contacts.

Passengers manage these contact lists so that journeys can be automatically
shared and emergency alerts routed to the right people.
"""
import uuid

from django.conf import settings
from django.db import models


class TrustedContact(models.Model):

    class ContactType(models.TextChoices):
        FAMILY = 'FAMILY', 'Family Member'
        FRIEND = 'FRIEND', 'Friend'
        EMERGENCY = 'EMERGENCY', 'Emergency Contact'

    class Relationship(models.TextChoices):
        PARENT = 'PARENT', 'Parent'
        SPOUSE = 'SPOUSE', 'Spouse'
        CHILD = 'CHILD', 'Child'
        SIBLING = 'SIBLING', 'Sibling'
        GUARDIAN = 'GUARDIAN', 'Guardian'
        OTHER = 'OTHER', 'Other'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='trusted_contacts',
    )
    contact_type = models.CharField(max_length=12, choices=ContactType.choices)
    # For FAMILY contacts; blank for FRIEND / EMERGENCY.
    relationship = models.CharField(
        max_length=10, choices=Relationship.choices, blank=True,
    )
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)

    # Emergency contact priority flags (Story 3).
    is_primary_emergency = models.BooleanField(default=False)
    is_secondary_emergency = models.BooleanField(default=False)

    # Default: notify this contact when a journey is started (Story 4/5).
    notify_on_journey = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['contact_type', 'name']
        indexes = [
            models.Index(fields=['owner', 'contact_type']),
        ]

    def __str__(self):
        return f'{self.name} ({self.contact_type}) — owner:{self.owner_id}'
