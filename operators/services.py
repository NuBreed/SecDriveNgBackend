"""Transport operator / organization verification logic."""
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from common.models import VerificationDocument
from common.services import verification
from kyc.models import ReviewEvent, VerificationStatus
from notifications.models import Notification
from notifications.services import notify
from operators.models import OperatorVerification


@transaction.atomic
def submit_operator_verification(user, organization_name, cac_number, contact_info,
                                 cac_certificate, proof_of_address, representative_id,
                                 certification_expiry=None):
    req, _ = OperatorVerification.objects.update_or_create(
        user=user,
        defaults={
            'organization_name': organization_name,
            'cac_number': cac_number,
            'contact_info': contact_info or '',
            'certification_expiry': certification_expiry,
            'status': OperatorVerification.Status.PENDING,
            'is_verified': False,
            'rejection_reason': '',
            'reviewed_at': None,
            'reviewed_by': None,
        },
    )
    verification.clear_documents(req)
    verification.attach_document(req, user, VerificationDocument.DocType.CAC_CERTIFICATE,
                                 cac_certificate, document_number=cac_number,
                                 expiry_date=certification_expiry)
    verification.attach_document(req, user, VerificationDocument.DocType.PROOF_OF_ADDRESS, proof_of_address)
    verification.attach_document(req, user, VerificationDocument.DocType.REP_ID, representative_id)

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
    _finalize(req, admin, OperatorVerification.Status.APPROVED)
    req.is_verified = True
    req.save(update_fields=['is_verified'])
    # Reflect operator role on the user account.
    user = req.user
    if user.role != User.Roles.OPERATOR:
        user.role = User.Roles.OPERATOR
        user.save(update_fields=['role'])
    verification.log_review(req, admin, ReviewEvent.Action.APPROVED)
    notify(user, 'Operator verified ✅', f'{req.organization_name} is verified.',
           type=Notification.Type.KYC_UPDATE, status=VerificationStatus.APPROVED)
    return req


@transaction.atomic
def reject(req, admin=None, reason=''):
    _finalize(req, admin, OperatorVerification.Status.REJECTED, reason)
    req.is_verified = False
    req.save(update_fields=['is_verified'])
    verification.log_review(req, admin, ReviewEvent.Action.REJECTED, reason)
    notify(req.user, 'Operator verification rejected', reason or 'Your submission was rejected.',
           type=Notification.Type.KYC_UPDATE, status=VerificationStatus.REJECTED)
    return req


@transaction.atomic
def request_more_info(req, admin=None, reason=''):
    _finalize(req, admin, OperatorVerification.Status.PENDING, reason)
    verification.log_review(req, admin, ReviewEvent.Action.MORE_INFO, reason)
    notify(req.user, 'More information required',
           reason or 'Additional documents are needed for operator verification.',
           type=Notification.Type.KYC_UPDATE, status=VerificationStatus.MORE_INFO)
    return req


@transaction.atomic
def suspend(req, admin=None, reason=''):
    _finalize(req, admin, OperatorVerification.Status.SUSPENDED, reason)
    req.is_verified = False
    req.save(update_fields=['is_verified'])
    verification.log_review(req, admin, ReviewEvent.Action.SUSPENDED, reason)
    notify(req.user, 'Operator suspended', reason or 'Your operator status was suspended.',
           type=Notification.Type.KYC_UPDATE, status=VerificationStatus.SUSPENDED)
    return req
