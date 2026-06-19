"""QR code generation, verification, revocation, and regeneration.

Design notes
------------
- Every verified driver/vehicle gets **one active QRCode row** at a time.
  ``get_or_create_*`` returns the existing active record rather than creating
  duplicates; regeneration atomically revokes the old record and creates a new
  one.
- The signed v2 token embeds the QRCode UUID so the verify path can look up the
  DB row and check revocation status, solving the statefulness gap in the old
  stateless token approach.
- All verify calls are logged in ``QRScan`` (Stories 10 & 12), regardless of
  whether the scan was valid or not.
"""
import uuid as _uuid_mod

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.utils import timezone

from kyc.services import qr_service
from qr_codes.models import QRCode, QRScan


class QREligibilityError(Exception):
    """Raised when an entity does not meet QR code eligibility criteria."""


# ─── generation ──────────────────────────────────────────────────────────────

def get_or_create_participant_qr(user) -> QRCode:
    """Return the active participant QR for ``user``, creating one if needed."""
    driver = getattr(user, 'driver', None)
    req = getattr(driver, 'verification', None) if driver else None
    if driver is None or req is None or not req.can_operate:
        raise QREligibilityError(
            'Driver must be verified with a valid license to generate a QR code.'
        )
    ct = ContentType.objects.get_for_model(driver)
    active = QRCode.objects.filter(
        entity_type=QRCode.EntityType.PARTICIPANT,
        content_type=ct, object_id=str(driver.pk),
        status=QRCode.Status.ACTIVE,
    ).first()
    return active if active is not None else _create(QRCode.EntityType.PARTICIPANT, driver)


def get_or_create_asset_qr(user, vehicle_pk) -> QRCode:
    """Return the active asset QR for the given vehicle, creating one if needed."""
    from vehicles.models import Vehicle
    vehicle = Vehicle.objects.filter(pk=vehicle_pk, owner=user).first()
    if vehicle is None:
        raise QREligibilityError('Vehicle not found or not owned by this user.')
    req = getattr(vehicle, 'verification', None)
    if req is None or not req.is_road_eligible:
        raise QREligibilityError(
            'Vehicle must be verified with a valid inspection to generate a QR code.'
        )
    ct = ContentType.objects.get_for_model(vehicle)
    active = QRCode.objects.filter(
        entity_type=QRCode.EntityType.ASSET,
        content_type=ct, object_id=str(vehicle.pk),
        status=QRCode.Status.ACTIVE,
    ).first()
    return active if active is not None else _create(QRCode.EntityType.ASSET, vehicle)


@transaction.atomic
def _create(entity_type: str, entity) -> QRCode:
    """Create a new QRCode record with a signed v2 token."""
    ct = ContentType.objects.get_for_model(entity)
    prev = QRCode.objects.filter(
        entity_type=entity_type, content_type=ct, object_id=str(entity.pk),
    ).order_by('-generation').first()
    generation = (prev.generation + 1) if prev else 1

    # Generate UUID first so it can be embedded in the signed token.
    qr_id = _uuid_mod.uuid4()
    token = qr_service.make_token_v2(qr_id, entity_type.lower(), entity.pk)

    return QRCode.objects.create(
        id=qr_id,
        entity_type=entity_type,
        content_type=ct,
        object_id=str(entity.pk),
        generation=generation,
        token=token,
    )


# ─── verification ─────────────────────────────────────────────────────────────

def verify_qr(token: str, scanner=None, ip=None, user_agent='',
              latitude=None, longitude=None) -> dict:
    """Decode a v2 QR token, check revocation, log the scan, return a summary.

    Always returns a dict with at least ``{'valid': bool, 'result': str, 'message': str}``.
    On success, adds entity-specific fields and a ``journey_eligible`` flag.
    """
    from django.core import signing

    scan_kw = dict(
        token_tried=token[:1024],
        scanned_by=scanner,
        ip_address=ip,
        user_agent=(user_agent or '')[:512],
        latitude=latitude,
        longitude=longitude,
    )

    # ── 1. Decode token ───────────────────────────────────────────────────────
    try:
        data = qr_service.read_token_v2(token)
    except signing.BadSignature:
        QRScan.objects.create(**scan_kw, result=QRScan.Result.INVALID_TOKEN)
        return _fail('INVALID_TOKEN', 'Invalid or tampered QR code.')

    qr_id = data.get('qr')

    # ── 2. Look up QRCode record ──────────────────────────────────────────────
    try:
        qr = QRCode.objects.get(id=qr_id)
    except (QRCode.DoesNotExist, Exception):
        QRScan.objects.create(**scan_kw, result=QRScan.Result.INVALID_TOKEN)
        return _fail('INVALID_TOKEN', 'QR code record not found.')

    scan_kw['qr_code'] = qr

    # ── 3. Check revocation ───────────────────────────────────────────────────
    if qr.status == QRCode.Status.REVOKED:
        QRScan.objects.create(**scan_kw, result=QRScan.Result.REVOKED)
        return _fail('REVOKED', 'This QR code has been revoked.', qr_id=str(qr.id))

    # ── 4. Resolve entity and build summary ───────────────────────────────────
    entity = qr.content_object
    if entity is None:
        QRScan.objects.create(**scan_kw, result=QRScan.Result.INVALID_TOKEN)
        return _fail('INVALID_TOKEN', 'Entity no longer exists.')

    if qr.entity_type == QRCode.EntityType.PARTICIPANT:
        summary = _participant_summary(qr, entity)
    else:
        summary = _asset_summary(qr, entity)

    summary['qr_id'] = str(qr.id)
    summary['generation'] = qr.generation

    # Strip non-serialisable objects before storing in metadata JSONField
    meta = {k: v for k, v in summary.items() if isinstance(v, (str, int, float, bool, list, dict, type(None)))}
    QRScan.objects.create(**scan_kw, result=summary['result'], metadata=meta)
    return summary


def _participant_summary(qr, driver) -> dict:
    from drivers.models import DriverVerification
    req = getattr(driver, 'verification', None)
    user = driver.user

    if req is None:
        return _fail('INELIGIBLE', 'Driver verification not found.')
    if req.status == DriverVerification.Status.SUSPENDED:
        return _fail('SUSPENDED', 'This driver is currently suspended.')
    if not req.can_operate:
        return _fail('INELIGIBLE', 'Driver license has expired or is invalid.')

    return {
        'valid': True,
        'result': QRScan.Result.VALID,
        'entity_type': 'participant',
        'participant': {
            'name': f'{user.first_name} {user.last_name}'.strip() or user.username,
            'photo_url': _photo_url_for_driver(driver),
            'participant_type': driver.participant_type,
            'participant_type_label': driver.get_participant_type_display(),
            'verification_status': req.status,
            'license_valid': not req.license_expired,
            'trust_score': user.trust_score,
            'active': req.can_operate,
        },
        'badges': _get_badges(user),
        'journey_eligible': req.can_operate,
        'message': 'Participant verified.',
    }


def _asset_summary(qr, vehicle) -> dict:
    from vehicles.models import VehicleVerification
    req = getattr(vehicle, 'verification', None)

    if req is None:
        return _fail('INELIGIBLE', 'Vehicle verification not found.')
    if req.status == VehicleVerification.Status.SUSPENDED:
        return _fail('SUSPENDED', 'This vehicle is currently suspended.')
    if not req.is_road_eligible:
        return _fail('INELIGIBLE', 'Vehicle inspection has expired.')

    return {
        'valid': True,
        'result': QRScan.Result.VALID,
        'entity_type': 'asset',
        'asset': {
            'registration_number': vehicle.registration_number,
            'vehicle_type': vehicle.vehicle_type,
            'brand': vehicle.brand,
            'model': vehicle.model,
            'year': vehicle.year,
            'verification_status': req.status,
            'inspection_status': 'VALID' if not req.inspection_expired else 'EXPIRED',
            'inspection_expiry': str(req.inspection_expiry) if req.inspection_expiry else None,
            'insurance_expiry': str(req.insurance_expiry) if req.insurance_expiry else None,
        },
        'badges': _get_vehicle_badges(vehicle),
        'journey_eligible': req.is_road_eligible,
        'message': 'Asset verified.',
    }


def _photo_url_for_driver(driver):
    """Download URL of the driver's SELFIE or PASSPORT_PHOTO (if any)."""
    from django.urls import reverse
    from common.models import VerificationDocument
    identity = getattr(driver.user, 'identity_verification', None)
    if identity is None:
        return None
    ct = ContentType.objects.get_for_model(identity)
    doc = VerificationDocument.objects.filter(
        content_type=ct, object_id=str(identity.pk),
        doc_type__in=[
            VerificationDocument.DocType.SELFIE,
            VerificationDocument.DocType.PASSPORT_PHOTO,
        ],
    ).first()
    return reverse('document-download', kwargs={'pk': doc.pk}) if doc else None


def _get_badges(user):
    from common.services.badges import badges_for
    return badges_for(user)


def _get_vehicle_badges(vehicle):
    from common.services.badges import badges_for_vehicle
    return badges_for_vehicle(vehicle)


def _fail(result_code: str, message: str, **extra) -> dict:
    return {'valid': False, 'result': result_code, 'message': message, **extra}


# ─── revocation (Story 8) ─────────────────────────────────────────────────────

@transaction.atomic
def revoke_qr(qr_code: QRCode, admin=None, reason: str = '') -> QRCode:
    """Mark a QR code as revoked. Idempotent if already revoked."""
    if qr_code.status == QRCode.Status.REVOKED:
        return qr_code
    qr_code.status = QRCode.Status.REVOKED
    qr_code.revoked_at = timezone.now()
    qr_code.revoked_by = admin
    qr_code.revoke_reason = reason
    qr_code.save(update_fields=['status', 'revoked_at', 'revoked_by', 'revoke_reason'])
    return qr_code


# ─── regeneration (Story 9) ───────────────────────────────────────────────────

@transaction.atomic
def regenerate_qr(qr_code: QRCode, requester=None,
                  reason: str = 'Compromised QR') -> QRCode:
    """Revoke the old QR and issue a fresh one for the same entity."""
    revoke_qr(qr_code, admin=requester, reason=reason)
    entity = qr_code.content_object
    if entity is None:
        raise QREligibilityError('Entity no longer exists; cannot regenerate.')
    # Re-check eligibility before issuing a new QR.
    entity_type = qr_code.entity_type
    if entity_type == QRCode.EntityType.PARTICIPANT:
        req = getattr(entity, 'verification', None)
        if req is None or not req.can_operate:
            raise QREligibilityError('Driver is no longer eligible for a QR code.')
    else:
        req = getattr(entity, 'verification', None)
        if req is None or not req.is_road_eligible:
            raise QREligibilityError('Vehicle is no longer eligible for a QR code.')
    return _create(entity_type, entity)
