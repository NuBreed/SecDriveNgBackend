import uuid

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone

from common.storage import private_storage


def _document_upload_path(instance, filename):
    return f'kyc/{instance.doc_type.lower()}/{instance.id}_{filename}'


class VerificationDocument(models.Model):
    """A securely-stored document attached to any verification request.

    Linked to the owning request (IdentityVerification, DriverVerification,
    VehicleVerification, OperatorVerification) via a generic relation so the
    same model, private storage, download endpoint, and expiry logic are reused
    across every verification flow.
    """

    class DocType(models.TextChoices):
        NATIONAL_ID = 'NATIONAL_ID'
        VOTER_CARD = 'VOTER_CARD'
        PASSPORT = 'PASSPORT'
        DRIVER_LICENSE = 'DRIVER_LICENSE'
        PASSPORT_PHOTO = 'PASSPORT_PHOTO'
        SELFIE = 'SELFIE'
        VEHICLE_REGISTRATION = 'VEHICLE_REGISTRATION'
        PROOF_OF_OWNERSHIP = 'PROOF_OF_OWNERSHIP'
        INSPECTION_CERTIFICATE = 'INSPECTION_CERTIFICATE'
        INSURANCE = 'INSURANCE'
        CAC_CERTIFICATE = 'CAC_CERTIFICATE'
        PROOF_OF_ADDRESS = 'PROOF_OF_ADDRESS'
        REP_ID = 'REP_ID'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='verification_documents',
    )

    # Generic link to the owning verification request.
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.CharField(max_length=64, null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')

    doc_type = models.CharField(max_length=32, choices=DocType.choices)
    file = models.FileField(storage=private_storage, upload_to=_document_upload_path)
    document_number = models.CharField(max_length=100, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-uploaded_at']
        indexes = [
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['owner', 'doc_type']),
            models.Index(fields=['expiry_date']),
        ]

    @property
    def is_expired(self):
        return self.expiry_date is not None and self.expiry_date < timezone.now().date()

    def expires_soon(self, days):
        if self.expiry_date is None:
            return False
        delta = (self.expiry_date - timezone.now().date()).days
        return 0 <= delta <= days

    def __str__(self):
        return f'{self.doc_type} ({self.owner})'
