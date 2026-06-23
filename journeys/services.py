"""Journey lifecycle service layer.

All state transitions go through this module so that:
- Pre/post conditions are validated in one place.
- Timeline events are always written alongside state changes.
- WebSocket broadcasts are always triggered from the service (not views).
"""
from django.db import transaction
from django.utils import timezone

from journeys.models import Journey, JourneyEvent, JourneyLocation


class JourneyError(Exception):
    """Raised when a transition is invalid for the current state."""


# ─── helpers ──────────────────────────────────────────────────────────────────

def _log(journey, event_type, actor=None, **meta):
    JourneyEvent.objects.create(
        journey=journey, event_type=event_type, actor=actor,
        metadata=meta or {},
    )
    return journey


def _push_to_user(user_pk, message):
    """Send a group message to a user's personal notification channel.

    Non-blocking — a missing channel layer must never crash an HTTP request.
    """
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(
            f'notifications_{user_pk}',
            {'type': 'notification.message', **message},
        )
    except Exception:
        pass


def _broadcast(journey, event_type, data=None):
    """Send a Channels group message to the journey's room.

    Deliberately non-blocking: a failure to push (e.g. Redis not running in
    tests) must never break the HTTP request.
    """
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(
            f'journey_{journey.id}',
            {
                'type': 'journey.event',
                'event': event_type,
                'journey_id': str(journey.id),
                'status': journey.status,
                'data': data or {},
            },
        )
    except Exception:
        pass


# ─── creation (Story 1) ───────────────────────────────────────────────────────

@transaction.atomic
def create_journey(passenger, participant_token, asset_token='',
                   group_size=1,
                   origin_lat=None, origin_lng=None, origin_address='',
                   destination_lat=None, destination_lng=None, destination_address='') -> Journey:
    """Verify participant QR token, then create a CREATED journey.

    asset_token is optional: if omitted the driver's first verified vehicle is
    used automatically so passengers only need to scan a single QR code.
    """
    from qr_codes import services as qr_svc
    from qr_codes.models import QRCode

    p_result = qr_svc.verify_qr(participant_token, scanner=passenger)
    if not p_result.get('valid'):
        raise JourneyError(
            f'Participant QR invalid: {p_result.get("message", "Unknown error")}'
        )

    p_qr = QRCode.objects.get(token=participant_token)
    driver = p_qr.content_object

    # Resolve vehicle — either from explicit asset token or driver's verified vehicle.
    if asset_token:
        a_result = qr_svc.verify_qr(asset_token, scanner=passenger)
        if not a_result.get('valid'):
            raise JourneyError(
                f'Asset QR invalid: {a_result.get("message", "Unknown error")}'
            )
        a_qr = QRCode.objects.get(token=asset_token)
        vehicle = a_qr.content_object
    else:
        vehicle = (
            driver.user.vehicles_owned.filter(is_verified=True).first()
            or driver.user.vehicles_owned.first()
        )
        if vehicle is None:
            raise JourneyError('Driver has no registered vehicle.')
        a_qr = getattr(vehicle, 'qr_code', None)

    journey = Journey.objects.create(
        passenger=passenger,
        driver=driver,
        vehicle=vehicle,
        participant_qr=p_qr,
        asset_qr=a_qr,  # may be None when auto-resolved
        status=Journey.Status.CREATED,
        group_size=max(1, int(group_size)),
        origin_lat=origin_lat,
        origin_lng=origin_lng,
        origin_address=origin_address or '',
        destination_lat=destination_lat,
        destination_lng=destination_lng,
        destination_address=destination_address or '',
    )
    _log(journey, JourneyEvent.EventType.CREATED, actor=passenger)
    _broadcast(journey, 'journey.created')

    # ── Notify driver of the incoming ride request ──────────────────────────
    passenger_name = (
        f'{passenger.first_name} {passenger.last_name}'.strip()
        or passenger.email
    )
    _push_to_user(driver.user_id, {
        'event': 'ride_request',
        'journey_id': str(journey.id),
        'passenger': {
            'name': passenger_name,
            'phone': getattr(passenger, 'phone_number', '') or '',
        },
        'origin_address': journey.origin_address or '',
        'destination_address': journey.destination_address or '',
        'group_size': journey.group_size,
        'created_at': journey.created_at.isoformat(),
    })
    from notifications.services import notify
    from notifications.models import Notification
    notify(
        driver.user,
        title='New Ride Request',
        body=f'{passenger_name} wants to ride with you.',
        type=Notification.Type.RIDE,
        journey_id=str(journey.id),
    )

    # FCM push (works when app is in background or killed)
    try:
        from notifications.fcm import send_to_device
        prefs = getattr(driver.user, 'notification_prefs', None)
        push_token = prefs.push_token if prefs else None
        if push_token:
            send_to_device(
                token=push_token,
                title='🚗 New Ride Request',
                body=f'{passenger_name} wants to ride with you. Tap to respond.',
                data={
                    'type':                'ride_request',
                    'journey_id':          str(journey.id),
                    'passenger_name':      passenger_name,
                    'passenger_phone':     getattr(passenger, 'phone_number', '') or '',
                    'origin_address':      journey.origin_address or '',
                    'destination_address': journey.destination_address or '',
                    'group_size':          str(journey.group_size),
                },
            )
    except Exception:
        pass
    # ───────────────────────────────────────────────────────────────────────

    return journey


# ─── driver accept / decline (QR-scan ride requests) ─────────────────────────

@transaction.atomic
def accept_journey(journey, driver_user) -> Journey:
    """Driver accepts an incoming ride request (CREATED → VERIFIED)."""
    if journey.driver.user_id != driver_user.pk:
        raise JourneyError('Only the journey driver may accept this request.')
    if journey.status != Journey.Status.CREATED:
        raise JourneyError(f'Cannot accept a journey in status {journey.status}.')

    journey.status = Journey.Status.VERIFIED
    journey.save(update_fields=['status'])
    _log(journey, JourneyEvent.EventType.ALERT, actor=driver_user,
         detail='driver_accepted')
    _broadcast(journey, 'journey.accepted')
    _push_to_user(journey.passenger_id, {
        'event': 'ride_accepted',
        'journey_id': str(journey.id),
        'message': 'Your driver accepted the ride. Board when ready.',
    })
    from notifications.services import notify
    from notifications.models import Notification
    driver_name = (
        f'{driver_user.first_name} {driver_user.last_name}'.strip()
        or 'Your driver'
    )
    notify(
        journey.passenger,
        title='Ride Accepted',
        body=f'{driver_name} accepted your ride request. Board when ready.',
        type=Notification.Type.RIDE,
        journey_id=str(journey.id),
    )
    return journey


@transaction.atomic
def decline_journey(journey, driver_user) -> Journey:
    """Driver declines an incoming ride request (CREATED → CANCELLED)."""
    if journey.driver.user_id != driver_user.pk:
        raise JourneyError('Only the journey driver may decline this request.')
    if journey.status != Journey.Status.CREATED:
        raise JourneyError(f'Cannot decline a journey in status {journey.status}.')

    journey.status = Journey.Status.CANCELLED
    journey.cancelled_at = timezone.now()
    journey.cancellation_reason = 'driver_declined'
    journey.save(update_fields=['status', 'cancelled_at', 'cancellation_reason'])
    _log(journey, JourneyEvent.EventType.CANCELLED, actor=driver_user,
         reason='driver_declined')
    _broadcast(journey, 'journey.declined')
    _push_to_user(journey.passenger_id, {
        'event': 'ride_declined',
        'journey_id': str(journey.id),
        'message': 'Your driver declined the ride request. Please try another driver.',
    })
    from notifications.services import notify
    from notifications.models import Notification
    notify(
        journey.passenger,
        title='Ride Declined',
        body='Your driver declined the ride request. Please try another driver.',
        type=Notification.Type.RIDE,
        journey_id=str(journey.id),
    )
    return journey


# ─── destination (Story 2) ────────────────────────────────────────────────────

@transaction.atomic
def set_destination(journey, passenger, origin_lat, origin_lng, origin_address,
                    dest_lat, dest_lng, dest_address,
                    estimated_distance_m=None, estimated_duration_s=None) -> Journey:
    if journey.is_terminal:
        raise JourneyError('Cannot update destination on a completed/cancelled journey.')
    if journey.passenger_id != passenger.pk:
        raise JourneyError('Only the journey passenger may set the destination.')

    journey.origin_lat = origin_lat
    journey.origin_lng = origin_lng
    journey.origin_address = origin_address
    journey.destination_lat = dest_lat
    journey.destination_lng = dest_lng
    journey.destination_address = dest_address
    journey.estimated_distance_m = estimated_distance_m
    journey.estimated_duration_s = estimated_duration_s
    journey.save(update_fields=[
        'origin_lat', 'origin_lng', 'origin_address',
        'destination_lat', 'destination_lng', 'destination_address',
        'estimated_distance_m', 'estimated_duration_s',
    ])
    _log(journey, JourneyEvent.EventType.DESTINATION_SET, actor=passenger,
         destination_address=dest_address)
    _broadcast(journey, 'destination.set')
    return journey


# ─── start (Story 3) ──────────────────────────────────────────────────────────

@transaction.atomic
def start_journey(journey, passenger) -> Journey:
    if journey.status not in (Journey.Status.CREATED, Journey.Status.VERIFIED):
        raise JourneyError(f'Cannot start a journey in status {journey.status}.')
    if journey.passenger_id != passenger.pk:
        raise JourneyError('Only the journey passenger may start the journey.')

    journey.status = Journey.Status.ACTIVE
    journey.started_at = timezone.now()
    journey.save(update_fields=['status', 'started_at'])
    _log(journey, JourneyEvent.EventType.STARTED, actor=passenger,
         lat=journey.origin_lat, lng=journey.origin_lng)
    _broadcast(journey, 'journey.started')
    # Sharing + iSafePass subscription — outside the atomic block so a
    # sharing failure does not roll back the journey start.
    from journeys.sharing import on_journey_started
    transaction.on_commit(lambda: on_journey_started(journey))
    return journey


# ─── pause (Story 8) ──────────────────────────────────────────────────────────

@transaction.atomic
def pause_journey(journey, passenger, reason='') -> Journey:
    if journey.status != Journey.Status.ACTIVE:
        raise JourneyError('Only an active journey can be paused.')
    if journey.passenger_id != passenger.pk:
        raise JourneyError('Only the journey passenger may pause the journey.')

    journey.status = Journey.Status.PAUSED
    journey.paused_at = timezone.now()
    journey.pause_reason = reason
    journey.save(update_fields=['status', 'paused_at', 'pause_reason'])
    _log(journey, JourneyEvent.EventType.PAUSED, actor=passenger, reason=reason)
    _broadcast(journey, 'journey.paused', {'reason': reason})
    return journey


# ─── resume (Story 9) ─────────────────────────────────────────────────────────

@transaction.atomic
def resume_journey(journey, passenger) -> Journey:
    if journey.status != Journey.Status.PAUSED:
        raise JourneyError('Only a paused journey can be resumed.')
    if journey.passenger_id != passenger.pk:
        raise JourneyError('Only the journey passenger may resume the journey.')

    journey.status = Journey.Status.ACTIVE
    journey.paused_at = None
    journey.pause_reason = ''
    journey.save(update_fields=['status', 'paused_at', 'pause_reason'])
    _log(journey, JourneyEvent.EventType.RESUMED, actor=passenger)
    _broadcast(journey, 'journey.resumed')
    return journey


# ─── complete (Story 10) ──────────────────────────────────────────────────────

@transaction.atomic
def complete_journey(journey, passenger) -> Journey:
    if journey.status not in (Journey.Status.ACTIVE, Journey.Status.PAUSED):
        raise JourneyError(f'Cannot complete a journey in status {journey.status}.')
    if journey.passenger_id != passenger.pk:
        raise JourneyError('Only the journey passenger may complete the journey.')

    journey.status = Journey.Status.COMPLETED
    journey.completed_at = timezone.now()
    journey.save(update_fields=['status', 'completed_at'])
    _log(journey, JourneyEvent.EventType.COMPLETED, actor=passenger)
    _broadcast(journey, 'journey.completed')
    from journeys.sharing import on_journey_event, unsubscribe_isafepass
    transaction.on_commit(lambda: (
        on_journey_event(journey, 'journey.completed', {
            'message': 'Journey completed.',
            'completed_at': str(journey.completed_at),
        }),
        unsubscribe_isafepass(journey),
    ))
    return journey


# ─── cancel (Story 11) ────────────────────────────────────────────────────────

@transaction.atomic
def cancel_journey(journey, passenger, reason='') -> Journey:
    if journey.is_terminal:
        raise JourneyError(f'Journey is already in terminal state {journey.status}.')
    if journey.passenger_id != passenger.pk and not getattr(passenger, 'is_staff', False):
        raise JourneyError('Only the journey passenger (or staff) may cancel the journey.')

    journey.status = Journey.Status.CANCELLED
    journey.cancelled_at = timezone.now()
    journey.cancellation_reason = reason
    journey.save(update_fields=['status', 'cancelled_at', 'cancellation_reason'])
    _log(journey, JourneyEvent.EventType.CANCELLED, actor=passenger, reason=reason)
    _broadcast(journey, 'journey.cancelled', {'reason': reason})
    return journey


# ─── location (Story 5) ───────────────────────────────────────────────────────

@transaction.atomic
def record_location(journey, latitude, longitude, speed=None, heading=None,
                    accuracy=None, altitude=None, client_timestamp=None) -> JourneyLocation:
    if journey.status != Journey.Status.ACTIVE:
        raise JourneyError('Location updates are only accepted for active journeys.')

    # Dedup: if the same client_timestamp was already recorded, skip (Story 13).
    if client_timestamp is not None:
        if JourneyLocation.objects.filter(
            journey=journey, client_timestamp=client_timestamp
        ).exists():
            return JourneyLocation.objects.get(
                journey=journey, client_timestamp=client_timestamp,
            )

    loc = JourneyLocation.objects.create(
        journey=journey,
        latitude=latitude, longitude=longitude,
        speed=speed, heading=heading,
        accuracy=accuracy, altitude=altitude,
        client_timestamp=client_timestamp,
    )
    # Broadcast lightweight update to tracking channel.
    _broadcast(journey, 'location.updated', {
        'lat': latitude, 'lng': longitude,
        'speed': speed, 'heading': heading,
    })
    # Trigger route intelligence analysis outside the atomic block.
    _loc_id = str(loc.id)
    _journey_id = str(journey.id)
    transaction.on_commit(
        lambda: _trigger_analysis(_journey_id, _loc_id)
    )
    return loc


def _trigger_analysis(journey_id: str, location_id: str):
    """Schedule (or run inline) route intelligence analysis for a new location ping."""
    try:
        from route_intelligence.tasks import analyze_journey_location
        analyze_journey_location.delay(journey_id, location_id)
    except Exception:
        pass
