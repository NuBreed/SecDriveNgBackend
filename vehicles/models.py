from django.db import models


class Vehicle(models.Model):

    owner = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='vehicles_owned',
        null=True,
        blank=True,
    )

    registration_number = models.CharField(
        max_length=50,
        unique=True
    )

    vehicle_type = models.CharField(
        max_length=50
    )

    brand = models.CharField(
        max_length=100
    )

    model = models.CharField(
        max_length=100
    )

    year = models.PositiveIntegerField()

    is_verified = models.BooleanField(
        default=False
    )

    def __str__(self):
        return f'{self.registration_number} ({self.brand} {self.model})'


class VehicleVerification(models.Model):
    """Vehicle registration + inspection verification."""

    class Status(models.TextChoices):
        PENDING = "PENDING"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"
        SUSPENDED = "SUSPENDED"

    vehicle = models.OneToOneField(
        Vehicle, on_delete=models.CASCADE, related_name='verification',
    )
    owner = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='vehicle_verifications',
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING,
    )
    inspection_expiry = models.DateField(null=True, blank=True)
    insurance_expiry = models.DateField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vehicle_reviews',
    )
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def inspection_expired(self):
        from django.utils import timezone
        return self.inspection_expiry is not None and self.inspection_expiry < timezone.now().date()

    @property
    def is_road_eligible(self):
        return self.status == self.Status.APPROVED and not self.inspection_expired

    def __str__(self):
        return f'VehicleVerification({self.vehicle}, {self.status})'