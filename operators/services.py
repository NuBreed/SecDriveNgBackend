"""Operator services: KYC verification + Fleet Management (Epics 3 & 8)."""
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from common.models import VerificationDocument
from common.services import verification
from kyc.models import ReviewEvent, VerificationStatus
from notifications.models import Notification
from notifications.services import notify
from operators.models import (
    Branch, FleetAsset, FleetParticipant, FleetSafetyScore,
    OperatorMembership, OperatorVerification, ParticipantAssetAssignment,
    TransportOperator,
)


# ── KYC / Verification services (unchanged from Epic 3) ──────────────────────

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


# ── Fleet Management services (Epic 8) ───────────────────────────────────────

@transaction.atomic
def register_operator(user, organization_name, registration_number, business_type,
                      contact_phone='', contact_email='', contact_address='',
                      verification_obj=None):
    """Create a TransportOperator and make the user the OWNER member."""
    op = TransportOperator.objects.create(
        owner=user,
        verification=verification_obj,
        organization_name=organization_name,
        registration_number=registration_number,
        business_type=business_type,
        contact_phone=contact_phone,
        contact_email=contact_email,
        contact_address=contact_address,
    )
    OperatorMembership.objects.create(
        operator=op, user=user, role=OperatorMembership.Role.OWNER,
    )
    return op


@transaction.atomic
def create_branch(operator, name, branch_type=Branch.BranchType.LOCAL,
                  parent=None, address='', phone=''):
    return Branch.objects.create(
        operator=operator, name=name, branch_type=branch_type,
        parent=parent, address=address, phone=phone,
    )


@transaction.atomic
def add_member(operator, user, role=OperatorMembership.Role.VIEWER, branch=None):
    membership, created = OperatorMembership.objects.get_or_create(
        operator=operator, user=user,
        defaults={'role': role, 'branch': branch, 'is_active': True},
    )
    if not created:
        membership.role = role
        membership.branch = branch
        membership.is_active = True
        membership.save(update_fields=['role', 'branch', 'is_active'])
    return membership


@transaction.atomic
def assign_participant(operator, user, participant_type, branch=None, added_by=None):
    """Assign a user as a fleet participant (driver/rider/personnel)."""
    from drivers.models import Driver
    driver = None
    if participant_type in (FleetParticipant.ParticipantType.DRIVER,
                            FleetParticipant.ParticipantType.RIDER):
        driver = Driver.objects.filter(user=user).first()

    participant, created = FleetParticipant.objects.get_or_create(
        operator=operator, user=user,
        defaults={
            'driver': driver,
            'branch': branch,
            'participant_type': participant_type,
            'status': FleetParticipant.Status.ACTIVE,
            'added_by': added_by,
        },
    )
    if not created:
        participant.status = FleetParticipant.Status.ACTIVE
        participant.participant_type = participant_type
        participant.suspension_reason = ''
        if driver:
            participant.driver = driver
        participant.save(update_fields=[
            'status', 'participant_type', 'suspension_reason', 'driver', 'updated_at',
        ])
    return participant


@transaction.atomic
def suspend_participant(participant, reason=''):
    participant.status = FleetParticipant.Status.SUSPENDED
    participant.suspension_reason = reason
    participant.save(update_fields=['status', 'suspension_reason', 'updated_at'])
    # Deactivate all current asset assignments.
    participant.asset_assignments.filter(is_active=True).update(
        is_active=False, unassigned_at=timezone.now(),
    )
    return participant


@transaction.atomic
def remove_participant(participant):
    participant.status = FleetParticipant.Status.REMOVED
    participant.save(update_fields=['status', 'updated_at'])
    participant.asset_assignments.filter(is_active=True).update(
        is_active=False, unassigned_at=timezone.now(),
    )
    return participant


@transaction.atomic
def add_fleet_asset(operator, vehicle, branch=None, added_by=None):
    asset, created = FleetAsset.objects.get_or_create(
        operator=operator, vehicle=vehicle,
        defaults={'branch': branch, 'status': FleetAsset.Status.ACTIVE, 'added_by': added_by},
    )
    if not created:
        asset.status = FleetAsset.Status.ACTIVE
        asset.save(update_fields=['status', 'updated_at'])
    return asset


@transaction.atomic
def retire_fleet_asset(asset):
    asset.status = FleetAsset.Status.RETIRED
    asset.save(update_fields=['status', 'updated_at'])
    asset.participant_assignments.filter(is_active=True).update(
        is_active=False, unassigned_at=timezone.now(),
    )
    return asset


@transaction.atomic
def remove_fleet_asset(asset):
    asset.status = FleetAsset.Status.REMOVED
    asset.save(update_fields=['status', 'updated_at'])
    asset.participant_assignments.filter(is_active=True).update(
        is_active=False, unassigned_at=timezone.now(),
    )
    return asset


@transaction.atomic
def assign_participant_to_asset(participant, asset, assigned_by=None):
    """Assign a participant to an asset; closes any previous active assignment for that pair."""
    ParticipantAssetAssignment.objects.filter(
        participant=participant, asset=asset, is_active=True,
    ).update(is_active=False, unassigned_at=timezone.now())

    assignment = ParticipantAssetAssignment.objects.create(
        participant=participant,
        asset=asset,
        assigned_by=assigned_by,
    )
    if asset.status == FleetAsset.Status.ACTIVE:
        asset.status = FleetAsset.Status.ASSIGNED
        asset.save(update_fields=['status', 'updated_at'])
    return assignment


@transaction.atomic
def unassign_participant_from_asset(assignment):
    assignment.is_active = False
    assignment.unassigned_at = timezone.now()
    assignment.save(update_fields=['is_active', 'unassigned_at'])
    # If no more active assignments, revert asset to ACTIVE.
    still_assigned = assignment.asset.participant_assignments.filter(is_active=True).exists()
    if not still_assigned:
        assignment.asset.status = FleetAsset.Status.ACTIVE
        assignment.asset.save(update_fields=['status', 'updated_at'])
    return assignment


# ── Dashboard & read services ─────────────────────────────────────────────────

def _driver_ids_for_operator(operator):
    """Return Driver PKs for all active DRIVER/RIDER participants."""
    return list(
        FleetParticipant.objects.filter(
            operator=operator,
            status=FleetParticipant.Status.ACTIVE,
            driver__isnull=False,
        ).values_list('driver_id', flat=True)
    )


def get_fleet_dashboard(operator):
    """Aggregate data for Story 6 fleet dashboard."""
    from journeys.models import Journey
    from route_intelligence.models import JourneyRisk
    from accident_detection.models import AccidentEvent

    active_participants = FleetParticipant.objects.filter(
        operator=operator, status=FleetParticipant.Status.ACTIVE,
    ).count()
    active_assets = FleetAsset.objects.filter(
        operator=operator, status__in=[FleetAsset.Status.ACTIVE, FleetAsset.Status.ASSIGNED],
    ).count()

    driver_ids = _driver_ids_for_operator(operator)
    active_journeys = Journey.objects.filter(
        driver_id__in=driver_ids, status=Journey.Status.ACTIVE,
    ).count()

    safety_alerts = JourneyRisk.objects.filter(
        journey__driver_id__in=driver_ids,
        level__in=['HIGH', 'CRITICAL'],
    ).count()

    pending_incidents = AccidentEvent.objects.filter(
        journey__driver_id__in=driver_ids,
        confirmation_status=AccidentEvent.ConfirmationStatus.PENDING,
    ).count()

    safety_score = getattr(getattr(operator, 'safety_score', None), 'score', 0.0)

    return {
        'operator_id': str(operator.id),
        'organization_name': operator.organization_name,
        'fleet_safety_score': safety_score,
        'active_participants': active_participants,
        'active_assets': active_assets,
        'active_journeys': active_journeys,
        'safety_alerts': safety_alerts,
        'pending_incidents': pending_incidents,
    }


def get_live_fleet(operator):
    """Active journeys with last known location for Story 7."""
    from journeys.models import Journey

    driver_ids = _driver_ids_for_operator(operator)
    journeys = Journey.objects.filter(
        driver_id__in=driver_ids, status=Journey.Status.ACTIVE,
    ).select_related('driver__user', 'vehicle', 'passenger')

    result = []
    for j in journeys:
        loc = j.last_location
        result.append({
            'journey_id': str(j.id),
            'status': j.status,
            'participant': {
                'driver_id': j.driver_id,
                'name': j.driver.user.get_full_name(),
            },
            'asset': {
                'vehicle_id': j.vehicle_id,
                'registration': j.vehicle.registration_number,
            },
            'location': {
                'lat': loc.latitude if loc else None,
                'lng': loc.longitude if loc else None,
            } if loc else None,
        })
    return result


def get_safety_monitoring(operator):
    """Route deviations, high-risk journeys, warnings, incidents for Story 8."""
    from route_intelligence.models import RouteDeviation, JourneyRisk, JourneyWarning
    from accident_detection.models import AccidentEvent

    driver_ids = _driver_ids_for_operator(operator)

    deviations = RouteDeviation.objects.filter(
        journey__driver_id__in=driver_ids, is_resolved=False,
    ).select_related('journey').order_by('-created_at')[:50]

    high_risk = JourneyRisk.objects.filter(
        journey__driver_id__in=driver_ids, level__in=['HIGH', 'CRITICAL'],
    ).select_related('journey').order_by('-computed_at')[:20]

    warnings = JourneyWarning.objects.filter(
        journey__driver_id__in=driver_ids, is_resolved=False,
    ).select_related('journey').order_by('-created_at')[:50]

    incidents = AccidentEvent.objects.filter(
        journey__driver_id__in=driver_ids,
        confirmation_status__in=[
            AccidentEvent.ConfirmationStatus.PENDING,
            AccidentEvent.ConfirmationStatus.NEEDS_HELP,
            AccidentEvent.ConfirmationStatus.ESCALATED,
        ],
    ).select_related('journey').order_by('-detected_at')[:20]

    return {
        'unresolved_deviations': deviations.count(),
        'high_risk_journeys': high_risk.count(),
        'unresolved_warnings': warnings.count(),
        'active_incidents': incidents.count(),
    }


def get_compliance_status(operator):
    """License / inspection / insurance expiry monitoring for Story 9."""
    from django.utils import timezone
    from datetime import timedelta
    from drivers.models import DriverVerification
    from vehicles.models import VehicleVerification

    today = timezone.now().date()
    warn_date = today + timedelta(days=30)

    participant_users = FleetParticipant.objects.filter(
        operator=operator,
        status=FleetParticipant.Status.ACTIVE,
        participant_type__in=[
            FleetParticipant.ParticipantType.DRIVER,
            FleetParticipant.ParticipantType.RIDER,
        ],
    ).values_list('user_id', flat=True)

    expired_licenses = DriverVerification.objects.filter(
        driver__user_id__in=participant_users,
        license_expiry__lt=today,
        status=DriverVerification.Status.APPROVED,
    ).count()

    expiring_licenses = DriverVerification.objects.filter(
        driver__user_id__in=participant_users,
        license_expiry__range=(today, warn_date),
        status=DriverVerification.Status.APPROVED,
    ).count()

    asset_vehicle_ids = FleetAsset.objects.filter(
        operator=operator,
        status__in=[FleetAsset.Status.ACTIVE, FleetAsset.Status.ASSIGNED],
    ).values_list('vehicle_id', flat=True)

    expired_inspections = VehicleVerification.objects.filter(
        vehicle_id__in=asset_vehicle_ids,
        inspection_expiry__lt=today,
        status=VehicleVerification.Status.APPROVED,
    ).count()

    expiring_inspections = VehicleVerification.objects.filter(
        vehicle_id__in=asset_vehicle_ids,
        inspection_expiry__range=(today, warn_date),
        status=VehicleVerification.Status.APPROVED,
    ).count()

    expired_insurance = VehicleVerification.objects.filter(
        vehicle_id__in=asset_vehicle_ids,
        insurance_expiry__lt=today,
        status=VehicleVerification.Status.APPROVED,
    ).count()

    expiring_insurance = VehicleVerification.objects.filter(
        vehicle_id__in=asset_vehicle_ids,
        insurance_expiry__range=(today, warn_date),
        status=VehicleVerification.Status.APPROVED,
    ).count()

    return {
        'expired_licenses': expired_licenses,
        'expiring_licenses': expiring_licenses,
        'expired_inspections': expired_inspections,
        'expiring_inspections': expiring_inspections,
        'expired_insurance': expired_insurance,
        'expiring_insurance': expiring_insurance,
    }


def get_analytics(operator, days=30):
    """Journey volume, asset utilization, safety performance for Story 11."""
    from django.utils import timezone
    from datetime import timedelta
    from journeys.models import Journey
    from route_intelligence.models import RouteDeviation
    from accident_detection.models import AccidentEvent

    since = timezone.now() - timedelta(days=days)
    driver_ids = _driver_ids_for_operator(operator)

    journeys = Journey.objects.filter(driver_id__in=driver_ids, created_at__gte=since)
    total_journeys = journeys.count()
    completed = journeys.filter(status=Journey.Status.COMPLETED).count()

    assets = FleetAsset.objects.filter(
        operator=operator,
        status__in=[FleetAsset.Status.ACTIVE, FleetAsset.Status.ASSIGNED],
    )
    asset_count = assets.count()

    deviations = RouteDeviation.objects.filter(
        journey__driver_id__in=driver_ids, created_at__gte=since,
    ).count()

    incidents = AccidentEvent.objects.filter(
        journey__driver_id__in=driver_ids, detected_at__gte=since,
    ).count()

    # Per-participant performance
    from django.db.models import Count
    participant_perf = (
        Journey.objects.filter(driver_id__in=driver_ids, created_at__gte=since)
        .values('driver__user__first_name', 'driver__user__last_name', 'driver_id')
        .annotate(journey_count=Count('id'))
        .order_by('-journey_count')[:10]
    )

    return {
        'period_days': days,
        'journey_volume': total_journeys,
        'completed_journeys': completed,
        'completion_rate': round(completed / total_journeys * 100, 1) if total_journeys else 0.0,
        'asset_count': asset_count,
        'active_participants': FleetParticipant.objects.filter(
            operator=operator, status=FleetParticipant.Status.ACTIVE,
        ).count(),
        'route_deviations': deviations,
        'accident_events': incidents,
        'incident_rate': round(incidents / total_journeys * 100, 2) if total_journeys else 0.0,
        'top_participants': list(participant_perf),
    }


# ── Fleet Safety Score (Story 14) ─────────────────────────────────────────────

def compute_fleet_safety_score(operator):
    """Compute and persist a 0-100 safety score for the fleet."""
    from django.utils import timezone
    from datetime import timedelta
    from journeys.models import Journey
    from route_intelligence.models import RouteDeviation
    from accident_detection.models import AccidentEvent
    from drivers.models import DriverVerification
    from vehicles.models import VehicleVerification

    since = timezone.now() - timedelta(days=30)
    today = timezone.now().date()
    driver_ids = _driver_ids_for_operator(operator)

    journeys = Journey.objects.filter(driver_id__in=driver_ids, created_at__gte=since)
    total_journeys = journeys.count()
    completed = journeys.filter(status=Journey.Status.COMPLETED).count()

    # Incident factor: each accident costs 5 points, capped at 50.
    incident_count = AccidentEvent.objects.filter(
        journey__driver_id__in=driver_ids, detected_at__gte=since,
    ).count()
    incident_penalty = min(50.0, incident_count * 5.0)

    # Deviation factor: each HIGH/CRITICAL deviation costs 3 points, capped at 30.
    serious_deviations = RouteDeviation.objects.filter(
        journey__driver_id__in=driver_ids,
        created_at__gte=since,
        severity__in=['HIGH', 'CRITICAL'],
    ).count()
    deviation_penalty = min(30.0, serious_deviations * 3.0)

    # Compliance factor: expired docs cost 5 points each, capped at 20.
    participant_users = FleetParticipant.objects.filter(
        operator=operator, status=FleetParticipant.Status.ACTIVE,
    ).values_list('user_id', flat=True)
    asset_vehicle_ids = FleetAsset.objects.filter(
        operator=operator, status__in=[FleetAsset.Status.ACTIVE, FleetAsset.Status.ASSIGNED],
    ).values_list('vehicle_id', flat=True)
    expired_licenses = DriverVerification.objects.filter(
        driver__user_id__in=participant_users,
        license_expiry__lt=today, status=DriverVerification.Status.APPROVED,
    ).count()
    expired_vehicles = VehicleVerification.objects.filter(
        vehicle_id__in=asset_vehicle_ids,
        inspection_expiry__lt=today, status=VehicleVerification.Status.APPROVED,
    ).count()
    compliance_penalty = min(20.0, (expired_licenses + expired_vehicles) * 5.0)

    # Performance factor: bonus for high completion rate.
    completion_rate = completed / total_journeys if total_journeys else 0
    performance_bonus = completion_rate * 10.0  # up to +10

    score = 100.0 - incident_penalty - deviation_penalty - compliance_penalty + performance_bonus
    score = round(max(0.0, min(100.0, score)), 1)

    if score >= 80:
        level = FleetSafetyScore.Level.EXCELLENT
    elif score >= 60:
        level = FleetSafetyScore.Level.GOOD
    elif score >= 40:
        level = FleetSafetyScore.Level.FAIR
    else:
        level = FleetSafetyScore.Level.POOR

    fss, _ = FleetSafetyScore.objects.update_or_create(
        operator=operator,
        defaults={
            'score': score,
            'level': level,
            'incident_factor': incident_penalty,
            'deviation_factor': deviation_penalty,
            'compliance_factor': compliance_penalty,
            'performance_factor': performance_bonus,
        },
    )
    operator.fleet_safety_score = score
    operator.save(update_fields=['fleet_safety_score', 'updated_at'])
    return fss
