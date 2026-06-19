import random
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Roles(models.TextChoices):
        PASSENGER = "PASSENGER"
        DRIVER = "DRIVER"
        OPERATOR = "OPERATOR"
        ADMIN = "ADMIN"

    class VerificationLevel(models.IntegerChoices):
        UNVERIFIED = 0, "Unverified"
        BASIC = 1, "Basic (phone + email)"
        IDENTITY = 2, "Identity Verified"
        DRIVER = 3, "Verified Driver"

    uuid = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    email = models.EmailField(unique=True)

    phone = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True
    )

    role = models.CharField(
        max_length=20,
        choices=Roles.choices,
        default=Roles.PASSENGER
    )

    is_verified = models.BooleanField(default=False)

    # Tiered KYC level for the person (0-3); Level 4 "vehicle verified" is a
    # per-vehicle badge, not a user level.
    verification_level = models.IntegerField(
        choices=VerificationLevel.choices,
        default=VerificationLevel.UNVERIFIED,
    )

    # Cached trust score (0-100), recomputed by common.services.trust.
    trust_score = models.FloatField(default=0)

    # Linked identity providers
    google_linked = models.BooleanField(default=False)

    # Account lockout
    failed_login_count = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_locked_out(self):
        return self.locked_until is not None and timezone.now() < self.locked_until

    @property
    def isafepass_linked(self):
        return hasattr(self, 'isafepass_link')

    def __str__(self):
        return self.username


class OTP(models.Model):
    """One-time codes for account verification and password reset."""

    class Purpose(models.TextChoices):
        ACCOUNT_VERIFICATION = "ACCOUNT_VERIFICATION"
        PASSWORD_RESET = "PASSWORD_RESET"

    class Channel(models.TextChoices):
        SMS = "SMS"
        EMAIL = "EMAIL"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otps')
    purpose = models.CharField(max_length=32, choices=Purpose.choices)
    channel = models.CharField(max_length=8, choices=Channel.choices, default=Channel.SMS)
    code = models.CharField(max_length=10)
    attempts = models.PositiveIntegerField(default=0)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', 'purpose', 'is_used'])]

    @classmethod
    def generate_for(cls, user, purpose, channel=Channel.SMS):
        # Invalidate any outstanding codes of the same purpose first.
        cls.objects.filter(user=user, purpose=purpose, is_used=False).update(is_used=True)
        length = getattr(settings, 'OTP_LENGTH', 6)
        code = ''.join(str(random.randint(0, 9)) for _ in range(length))
        expires_at = timezone.now() + timedelta(
            minutes=getattr(settings, 'OTP_EXPIRY_MINUTES', 10)
        )
        return cls.objects.create(
            user=user, purpose=purpose, channel=channel, code=code, expires_at=expires_at,
        )

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    def __str__(self):
        state = 'used' if self.is_used else ('expired' if self.is_expired else 'active')
        return f'OTP({self.user.username}, {self.purpose}, {state})'


class Device(models.Model):
    """A device a user signs in from."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='devices')
    device_id = models.CharField(max_length=255, db_index=True)
    device_type = models.CharField(max_length=50, blank=True)
    platform = models.CharField(max_length=50, blank=True)
    app_version = models.CharField(max_length=50, blank=True)
    is_trusted = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-last_login_at', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'device_id'], name='uniq_user_device'),
        ]

    def __str__(self):
        return f'Device({self.user.username}, {self.device_id})'


class AuthEvent(models.Model):
    """Authentication audit trail: login history + security monitoring."""

    class Type(models.TextChoices):
        LOGIN = "LOGIN"
        LOGIN_FAILED = "LOGIN_FAILED"
        LOGOUT = "LOGOUT"
        REFRESH = "REFRESH"
        LOCKOUT = "LOCKOUT"
        PASSWORD_RESET = "PASSWORD_RESET"
        OTP_VERIFY_FAILED = "OTP_VERIFY_FAILED"
        REGISTER = "REGISTER"
        VERIFY = "VERIFY"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='auth_events', null=True, blank=True,
    )
    identifier_tried = models.CharField(max_length=255, blank=True)
    event_type = models.CharField(max_length=32, choices=Type.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    device_id = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['event_type', '-created_at']),
        ]

    def __str__(self):
        who = self.user.username if self.user else self.identifier_tried
        return f'AuthEvent({who}, {self.event_type})'


class ISafePassLink(models.Model):
    """Links a SecDrive account to an iSafePass identity."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='isafepass_link')
    isafepass_user_id = models.CharField(max_length=255, db_index=True)
    # Cached snapshot of emergency contacts / safety profile / trust network
    # pulled from the iSafePass bridge at link time.
    profile_snapshot = models.JSONField(default=dict, blank=True)
    linked_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'ISafePassLink({self.user.username} -> {self.isafepass_user_id})'
