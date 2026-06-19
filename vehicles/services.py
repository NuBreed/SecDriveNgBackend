"""Vehicle verification logic."""
from django.db import transaction
from django.utils import timezone

from common.models import VerificationDocument
from common.services import trust, verification
from kyc.models import ReviewEvent, VerificationStatus
from notifications.models import Notification
from notifications.services import notify
from vehicles.models import Vehicle, VehicleVerification


@transaction.atomic
def submit_vehicle_verification(user, vehicle_data, registration_doc, proof_of_ownership,
                                inspection_certificate=None, inspection_expiry=None,
                                insurance=None, insurance_expiry=None):
    """Register/refresh a vehicle and its verification request with documents."""
    vehicle, _ = Vehicle.objects.update_or_create(
        registration_number=vehicle_data['registration_number'],
        defaults={
            'owner': user,
            'vehicle_type': vehicle_data['vehicle_type'],
            'brand': vehicle_data['brand'],
            'model': vehicle_data['model'],
            'year': vehicle_data['year'],
        },
    )
    req, _ = VehicleVerification.objects.update_or_create(
        vehicle=vehicle,
        defaults={
            'owner': user,
            'status': VehicleVerification.Status.PENDING,
            'inspection_expiry': inspection_expiry,
            'insurance_expiry': insurance_expiry,
            'rejection_reason': '',
            'reviewed_at': None,
            'reviewed_by': None,
        },
    )
    verification.clear_documents(req)
    verification.attach_document(req, user, VerificationDocument.DocType.VEHICLE_REGISTRATION,
                                 registration_doc, document_number=vehicle.registration_number)
    verification.attach_document(req, user, VerificationDocument.DocType.PROOF_OF_OWNERSHIP, proof_of_ownership)
    if inspection_certificate is not None:
        verification.attach_document(req, user, VerificationDocument.DocType.INSPECTION_CERTIFICATE,
                                     inspection_certificate, expiry_date=inspection_expiry)
    if insurance is not None:
        verification.attach_document(req, user, VerificationDocument.DocType.INSURANCE,
                                     insurance, expiry_date=insurance_expiry)

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
    _finalize(req, admin, VehicleVerification.Status.APPROVED)
    vehicle = req.vehicle
    vehicle.is_verified = True
    vehicle.save(update_fields=['is_verified'])
    trust.recompute_and_store(req.owner)
    verification.log_review(req, admin, ReviewEvent.Action.APPROVED)
    notify(req.owner, 'Vehicle verified ✅', f'{vehicle.registration_number} is verified.',
           type=Notification.Type.KYC_UPDATE, status=VerificationStatus.APPROVED)
    return req


@transaction.atomic
def reject(req, admin=None, reason=''):
    _finalize(req, admin, VehicleVerification.Status.REJECTED, reason)
    vehicle = req.vehicle
    vehicle.is_verified = False
    vehicle.save(update_fields=['is_verified'])
    verification.log_review(req, admin, ReviewEvent.Action.REJECTED, reason)
    notify(req.owner, 'Vehicle verification rejected', reason or 'Your submission was rejected.',
           type=Notification.Type.KYC_UPDATE, status=VerificationStatus.REJECTED)
    return req


@transaction.atomic
def request_more_info(req, admin=None, reason=''):
    _finalize(req, admin, VehicleVerification.Status.PENDING, reason)
    verification.log_review(req, admin, ReviewEvent.Action.MORE_INFO, reason)
    notify(req.owner, 'More information required',
           reason or 'Additional documents are needed for vehicle verification.',
           type=Notification.Type.KYC_UPDATE, status=VerificationStatus.MORE_INFO)
    return req


@transaction.atomic
def suspend(req, admin=None, reason=''):
    _finalize(req, admin, VehicleVerification.Status.SUSPENDED, reason)
    vehicle = req.vehicle
    vehicle.is_verified = False
    vehicle.save(update_fields=['is_verified'])
    verification.log_review(req, admin, ReviewEvent.Action.SUSPENDED, reason)
    notify(req.owner, 'Vehicle suspended', reason or 'Your vehicle was suspended.',
           type=Notification.Type.KYC_UPDATE, status=VerificationStatus.SUSPENDED)
    return req
