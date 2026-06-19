from django.db import models


class OperatorVerification(models.Model):
    """Transport operator / organization verification."""

    class Status(models.TextChoices):
        PENDING = "PENDING"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"
        SUSPENDED = "SUSPENDED"

    user = models.OneToOneField(
        'accounts.User', on_delete=models.CASCADE, related_name='operator_verification',
    )
    organization_name = models.CharField(max_length=255)
    cac_number = models.CharField(max_length=100)
    contact_info = models.CharField(max_length=255, blank=True)
    certification_expiry = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING,
    )
    is_verified = models.BooleanField(default=False)
    rejection_reason = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='operator_reviews',
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'OperatorVerification({self.organization_name}, {self.status})'
