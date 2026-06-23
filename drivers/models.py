from django.db import models
from accounts.models import User


class Driver(models.Model):
    class VerificationStatus(models.TextChoices):
        PENDING = "PENDING"
        VERIFIED = "VERIFIED"
        REJECTED = "REJECTED"

    class ParticipantType(models.TextChoices):
        TAXI_DRIVER = 'TAXI_DRIVER', 'Taxi Driver'
        BUS_DRIVER = 'BUS_DRIVER', 'Bus Driver'
        KEKE_RIDER = 'KEKE_RIDER', 'Keke Rider'
        OKADA_RIDER = 'OKADA_RIDER', 'Okada Rider'
        SHUTTLE_DRIVER = 'SHUTTLE_DRIVER', 'Shuttle Driver'
        DELIVERY_RIDER = 'DELIVERY_RIDER', 'Delivery Rider'
        OTHER = 'OTHER', 'Other'

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE
    )

    license_number = models.CharField(
        max_length=100,
        unique=True
    )

    participant_type = models.CharField(
        max_length=20,
        choices=ParticipantType.choices,
        default=ParticipantType.OTHER,
        blank=True,
    )

    trust_score = models.FloatField(default=100)

    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return f'Driver({self.user})'


class DriverPresence(models.Model):
    """Real-time position beacon posted by a driver in monitoring mode.

    Upserted every few seconds while the driver has the monitoring screen open.
    Records older than 30 seconds are treated as offline.
    """
    driver     = models.OneToOneField(
        Driver, on_delete=models.CASCADE, related_name='presence',
    )
    lat        = models.FloatField()
    lng        = models.FloatField()
    speed_kmh  = models.FloatField(default=0.0)
    heading    = models.FloatField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Presence({self.driver}, {self.speed_kmh} km/h)'


class DriverVerification(models.Model):
    """Driver credential verification request."""

    class Status(models.TextChoices):
        PENDING = "PENDING"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"
        SUSPENDED = "SUSPENDED"

    driver = models.OneToOneField(
        Driver, on_delete=models.CASCADE, related_name='verification',
    )
    license_number = models.CharField(max_length=100)
    license_expiry = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING,
    )
    background_review_passed = models.BooleanField(default=False)
    rejection_reason = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='driver_reviews',
    )
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def license_expired(self):
        from django.utils import timezone
        return self.license_expiry is not None and self.license_expiry < timezone.now().date()

    @property
    def can_operate(self):
        return self.status == self.Status.APPROVED and not self.license_expired

    def __str__(self):
        return f'DriverVerification({self.driver}, {self.status})'