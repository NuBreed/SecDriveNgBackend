"""Reverification monitoring (Story 11).

A daily Celery beat task scans verification documents for expiry, flags entities
whose critical documents have lapsed (suspending their verified status so QR
codes stop being issued), and sends reminders ahead of expiry.
"""
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from common.models import VerificationDocument
from notifications.models import Notification
from notifications.services import notify

# Document types whose expiry must keep an entity's verification current.
_CRITICAL = {
    VerificationDocument.DocType.DRIVER_LICENSE,
    VerificationDocument.DocType.INSPECTION_CERTIFICATE,
    VerificationDocument.DocType.INSURANCE,
    VerificationDocument.DocType.CAC_CERTIFICATE,
}


@shared_task
def scan_expiring_documents():
    reminder_days = settings.VERIFICATION_REMINDER_DAYS
    expired_count = 0
    reminded_count = 0

    docs = VerificationDocument.objects.exclude(expiry_date__isnull=True)
    for doc in docs.iterator():
        if doc.is_expired and doc.doc_type in _CRITICAL:
            if _handle_expired(doc):
                expired_count += 1
        elif doc.expires_soon(reminder_days):
            notify(
                doc.owner,
                'Document expiring soon',
                f'Your {doc.get_doc_type_display()} expires on {doc.expiry_date}. '
                'Please re-verify to keep your status active.',
                type=Notification.Type.REVERIFICATION,
                doc_type=doc.doc_type,
                expiry_date=str(doc.expiry_date),
            )
            reminded_count += 1

    return {'expired': expired_count, 'reminded': reminded_count}


def _handle_expired(doc):
    """Suspend the verified status tied to an expired critical document."""
    request_obj = doc.content_object
    if request_obj is None:
        return False

    suspended = False
    model_name = request_obj.__class__.__name__

    if model_name == 'DriverVerification' and request_obj.status == 'APPROVED':
        request_obj.status = 'SUSPENDED'
        request_obj.save(update_fields=['status', 'updated_at'])
        driver = request_obj.driver
        driver.verification_status = 'PENDING'
        driver.save(update_fields=['verification_status'])
        suspended = True
    elif model_name == 'VehicleVerification' and request_obj.status == 'APPROVED':
        request_obj.status = 'SUSPENDED'
        request_obj.save(update_fields=['status', 'updated_at'])
        vehicle = request_obj.vehicle
        vehicle.is_verified = False
        vehicle.save(update_fields=['is_verified'])
        suspended = True
    elif model_name == 'OperatorVerification' and request_obj.status == 'APPROVED':
        request_obj.status = 'SUSPENDED'
        request_obj.is_verified = False
        request_obj.save(update_fields=['status', 'is_verified', 'updated_at'])
        suspended = True

    if suspended:
        notify(
            doc.owner,
            'Verification expired',
            f'Your {doc.get_doc_type_display()} expired on {doc.expiry_date}. '
            'Your verified status is suspended until you re-verify.',
            type=Notification.Type.REVERIFICATION,
            doc_type=doc.doc_type,
        )
    return suspended
