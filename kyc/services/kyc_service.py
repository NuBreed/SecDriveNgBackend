"""Identity KYC business logic. Mirrors iSafePass KYCService."""
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from common.models import VerificationDocument
from common.services import trust
from notifications.models import Notification
from notifications.services import notify
from kyc.models import IdentityVerification, ReviewEvent, VerificationStatus


def _attach_document(request_obj, owner, doc_type, file, document_number='', expiry_date=None):
    ct = ContentType.objects.get_for_model(request_obj)
    return VerificationDocument.objects.create(
        owner=owner,
        content_type=ct,
        object_id=str(request_obj.pk),
        doc_type=doc_type,
        file=file,
        document_number=document_number or '',
        expiry_date=expiry_date,
    )


@transaction.atomic
def submit_identity(user, primary_id_type, id_document, document_number='', selfie=None):
    """Create/refresh the identity request and attach documents."""
    req, _ = IdentityVerification.objects.update_or_create(
        user=user,
        defaults={
            'primary_id_type': primary_id_type,
            'status': VerificationStatus.PENDING,
            'rejection_reason': '',
            'reviewed_at': None,
            'reviewed_by': None,
        },
    )
    # Replace any previously-submitted docs for a clean resubmission.
    ct = ContentType.objects.get_for_model(req)
    VerificationDocument.objects.filter(content_type=ct, object_id=str(req.pk)).delete()

    _attach_document(req, user, primary_id_type, id_document, document_number)
    if selfie is not None:
        _attach_document(req, user, VerificationDocument.DocType.SELFIE, selfie)

    ReviewEvent.objects.create(
        content_type=ct, object_id=str(req.pk), action=ReviewEvent.Action.SUBMITTED,
    )
    return req


@transaction.atomic
def attach_selfie(user, selfie):
    """Add/replace the selfie on the user's identity request."""
    req = getattr(user, 'identity_verification', None)
    if req is None:
        req = IdentityVerification.objects.create(
            user=user, primary_id_type=IdentityVerification.IDType.NATIONAL_ID,
            status=VerificationStatus.PENDING,
        )
    ct = ContentType.objects.get_for_model(req)
    VerificationDocument.objects.filter(
        content_type=ct, object_id=str(req.pk), doc_type=VerificationDocument.DocType.SELFIE,
    ).delete()
    return _attach_document(req, user, VerificationDocument.DocType.SELFIE, selfie)


def _log(req, actor, action, reason=''):
    ct = ContentType.objects.get_for_model(req)
    ReviewEvent.objects.create(
        actor=actor, content_type=ct, object_id=str(req.pk), action=action, reason=reason,
    )


@transaction.atomic
def approve(req, admin=None):
    req.status = VerificationStatus.APPROVED
    req.rejection_reason = ''
    req.reviewed_at = timezone.now()
    req.reviewed_by = admin
    req.save(update_fields=['status', 'rejection_reason', 'reviewed_at', 'reviewed_by', 'updated_at'])

    user = req.user
    if user.verification_level < User.VerificationLevel.IDENTITY:
        user.verification_level = User.VerificationLevel.IDENTITY
        user.save(update_fields=['verification_level'])
    trust.recompute_and_store(user)

    _log(req, admin, ReviewEvent.Action.APPROVED)
    notify(user, 'Identity verified ✅',
           'Your identity has been verified.', type=Notification.Type.KYC_UPDATE,
           status=VerificationStatus.APPROVED)
    return req


@transaction.atomic
def reject(req, admin=None, reason=''):
    req.status = VerificationStatus.REJECTED
    req.rejection_reason = reason
    req.reviewed_at = timezone.now()
    req.reviewed_by = admin
    req.save(update_fields=['status', 'rejection_reason', 'reviewed_at', 'reviewed_by', 'updated_at'])
    _log(req, admin, ReviewEvent.Action.REJECTED, reason)
    notify(req.user, 'Identity verification rejected',
           reason or 'Your identity submission was rejected.',
           type=Notification.Type.KYC_UPDATE, status=VerificationStatus.REJECTED)
    return req


@transaction.atomic
def request_more_info(req, admin=None, reason=''):
    req.status = VerificationStatus.MORE_INFO
    req.rejection_reason = reason
    req.reviewed_at = timezone.now()
    req.reviewed_by = admin
    req.save(update_fields=['status', 'rejection_reason', 'reviewed_at', 'reviewed_by', 'updated_at'])
    _log(req, admin, ReviewEvent.Action.MORE_INFO, reason)
    notify(req.user, 'More information required',
           reason or 'Additional documents are needed to verify your identity.',
           type=Notification.Type.KYC_UPDATE, status=VerificationStatus.MORE_INFO)
    return req
