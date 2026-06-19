"""Driver verification logic (Stories 4, 5)."""
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from common.models import VerificationDocument
from common.services import trust, verification
from kyc.models import ReviewEvent, VerificationStatus
from notifications.models import Notification
from notifications.services import notify
from drivers.models import Driver, DriverVerification


class VerificationError(Exception):
    """Raised when a driver verification precondition is not met."""


@transaction.atomic
def submit_driver_verification(user, license_number, license_expiry,
                               national_id, driver_license, passport_photo=None, selfie=None):
    """Create/refresh the driver verification request and attach documents.

    Requires the user's identity to be approved first (Level 2).
    """
    if user.verification_level < User.VerificationLevel.IDENTITY:
        raise VerificationError('Identity verification must be approved before driver verification.')

    driver, _ = Driver.objects.get_or_create(
        user=user, defaults={'license_number': license_number},
    )
    req, _ = DriverVerification.objects.update_or_create(
        driver=driver,
        defaults={
            'license_number': license_number,
            'license_expiry': license_expiry,
            'status': DriverVerification.Status.PENDING,
            'rejection_reason': '',
            'reviewed_at': None,
            'reviewed_by': None,
        },
    )
    verification.clear_documents(req)
    verification.attach_document(req, user, VerificationDocument.DocType.NATIONAL_ID, national_id)
    verification.attach_document(
        req, user, VerificationDocument.DocType.DRIVER_LICENSE, driver_license,
        document_number=license_number, expiry_date=license_expiry,
    )
    if passport_photo is not None:
        verification.attach_document(req, user, VerificationDocument.DocType.PASSPORT_PHOTO, passport_photo)
    if selfie is not None:
        verification.attach_document(req, user, VerificationDocument.DocType.SELFIE, selfie)

    verification.log_review(req, None, ReviewEvent.Action.SUBMITTED)
    return req


def _finalize(req, admin, status_value, reason=''):
    req.status = status_value
    req.rejection_reason = reason
    req.reviewed_at = timezone.now()
    req.reviewed_by = admin
    req.save(update_fields=['status', 'rejection_reason', 'reviewed_at', 'reviewed_by', 'updated_at'])


@transaction.atomic
def approve(req, admin=None):
    _finalize(req, admin, DriverVerification.Status.APPROVED)
    driver = req.driver
    driver.verification_status = Driver.VerificationStatus.VERIFIED
    driver.license_number = req.license_number
    driver.save(update_fields=['verification_status', 'license_number'])

    user = driver.user
    if user.verification_level < User.VerificationLevel.DRIVER:
        user.verification_level = User.VerificationLevel.DRIVER
        user.save(update_fields=['verification_level'])
    trust.recompute_and_store(user)

    verification.log_review(req, admin, ReviewEvent.Action.APPROVED)
    notify(user, 'Driver verified ✅', 'Your driver credentials are verified.',
           type=Notification.Type.KYC_UPDATE, status=VerificationStatus.APPROVED)
    return req


@transaction.atomic
def reject(req, admin=None, reason=''):
    _finalize(req, admin, DriverVerification.Status.REJECTED, reason)
    driver = req.driver
    driver.verification_status = Driver.VerificationStatus.REJECTED
    driver.save(update_fields=['verification_status'])
    verification.log_review(req, admin, ReviewEvent.Action.REJECTED, reason)
    notify(driver.user, 'Driver verification rejected', reason or 'Your submission was rejected.',
           type=Notification.Type.KYC_UPDATE, status=VerificationStatus.REJECTED)
    return req


@transaction.atomic
def request_more_info(req, admin=None, reason=''):
    _finalize(req, admin, DriverVerification.Status.PENDING, reason)
    verification.log_review(req, admin, ReviewEvent.Action.MORE_INFO, reason)
    notify(req.driver.user, 'More information required',
           reason or 'Additional documents are needed for driver verification.',
           type=Notification.Type.KYC_UPDATE, status=VerificationStatus.MORE_INFO)
    return req


@transaction.atomic
def suspend(req, admin=None, reason=''):
    _finalize(req, admin, DriverVerification.Status.SUSPENDED, reason)
    driver = req.driver
    driver.verification_status = Driver.VerificationStatus.PENDING
    driver.save(update_fields=['verification_status'])
    verification.log_review(req, admin, ReviewEvent.Action.SUSPENDED, reason)
    notify(driver.user, 'Driver account suspended', reason or 'Your driver status was suspended.',
           type=Notification.Type.KYC_UPDATE, status=VerificationStatus.SUSPENDED)
    return req
