import logging
import time

from django.conf import settings
from django.utils import timezone

from accident_detection.models import AccidentEvent, EmergencyEscalation, SOSRequest

logger = logging.getLogger(__name__)

# ── configurable thresholds ────────────────────────────────────────────────────

def _cfg(key, default):
    return getattr(settings, key, default)

IMPACT_ACCEL_MS2 = lambda: _cfg('ACCIDENT_IMPACT_ACCEL_MS2', 15.0)      # m/s²
ROLLOVER_TILT_DEG = lambda: _cfg('ACCIDENT_ROLLOVER_TILT_DEG', 60.0)    # degrees
ROLLOVER_RATE_DEG = lambda: _cfg('ACCIDENT_ROLLOVER_RATE_DEG', 90.0)    # deg/s
SUDDEN_STOP_DELTA_MS = lambda: _cfg('ACCIDENT_SUDDEN_STOP_DELTA_MS', 8.0)  # m/s drop
SUDDEN_STOP_MIN_SPEED = lambda: _cfg('ACCIDENT_SUDDEN_STOP_MIN_SPEED', 5.0)  # m/s (~18 km/h)
CONFIRMATION_TIMEOUT_S = lambda: _cfg('ACCIDENT_CONFIRMATION_TIMEOUT_S', 30)
MAX_RETRIES = lambda: _cfg('ACCIDENT_ESCALATION_MAX_RETRIES', 3)
RETRY_DELAY_S = lambda: _cfg('ACCIDENT_RETRY_DELAY_S', 30)


# ── sensor-based detection (Stories 1-3) ──────────────────────────────────────

def process_sensor_data(journey, sensor: dict, last_location=None) -> list:
    """Analyse a single sensor payload and return a list of new AccidentEvents.

    sensor keys (all optional):
      acceleration_x/y/z  (m/s²)
      rotation_rate        (deg/s — scalar or per-axis: rx/ry/rz)
      tilt_angle           (degrees from vertical)
      speed                (m/s — current)
      lat / lng
    """
    events = []

    lat = sensor.get('lat') or sensor.get('latitude')
    lng = sensor.get('lng') or sensor.get('longitude')

    # 1. Impact detection (Story 1).
    accel = _total_acceleration(sensor)
    if accel is not None and accel >= IMPACT_ACCEL_MS2():
        event = _create_event(journey, 'IMPACT', lat, lng,
                              acceleration_magnitude=accel,
                              raw=sensor)
        _assign_impact_severity(event, accel)
        events.append(event)

    # 2. Rollover detection (Story 2).
    tilt = sensor.get('tilt_angle')
    rate = sensor.get('rotation_rate') or _total_rotation(sensor)
    if tilt is not None and abs(tilt) >= ROLLOVER_TILT_DEG():
        event = _create_event(journey, 'ROLLOVER', lat, lng,
                              tilt_angle=tilt, rotation_rate=rate,
                              raw=sensor)
        event.severity = 'CRITICAL'
        event.save(update_fields=['severity'])
        events.append(event)

    # 3. Sudden stop detection (Story 3).
    speed_now = sensor.get('speed')
    if speed_now is not None and last_location is not None:
        speed_before = last_location.speed or 0.0
        delta = speed_before - speed_now
        if speed_before >= SUDDEN_STOP_MIN_SPEED() and delta >= SUDDEN_STOP_DELTA_MS():
            event = _create_event(journey, 'SUDDEN_STOP', lat, lng,
                                  speed_before=speed_before,
                                  speed_after=speed_now, raw=sensor)
            event.severity = 'HIGH' if delta > 15 else 'MEDIUM'
            event.save(update_fields=['severity'])
            events.append(event)

    # For each detected event, promote to POSSIBLE_ACCIDENT and start countdown.
    for event in events:
        _start_confirmation_countdown(journey, event)

    return events


def _total_acceleration(sensor: dict):
    """Magnitude of the acceleration vector, or None if no data."""
    x, y, z = sensor.get('acceleration_x'), sensor.get('acceleration_y'), sensor.get('acceleration_z')
    if x is not None and y is not None and z is not None:
        return (x**2 + y**2 + z**2) ** 0.5
    return sensor.get('acceleration_magnitude')


def _total_rotation(sensor: dict):
    """Scalar rotation rate magnitude, or None if no data."""
    rx, ry, rz = sensor.get('rotation_x'), sensor.get('rotation_y'), sensor.get('rotation_z')
    if rx is not None and ry is not None and rz is not None:
        return (rx**2 + ry**2 + rz**2) ** 0.5
    return sensor.get('rotation_rate')


def _assign_impact_severity(event, accel: float):
    from accident_detection.models import AccidentEvent
    if accel >= 30:
        sev = AccidentEvent.Severity.CRITICAL
    elif accel >= 20:
        sev = AccidentEvent.Severity.HIGH
    else:
        sev = AccidentEvent.Severity.MEDIUM
    event.severity = sev
    event.save(update_fields=['severity'])


def _create_event(journey, event_type: str, lat, lng, **kwargs) -> 'AccidentEvent':
    from accident_detection.models import AccidentEvent
    raw = kwargs.pop('raw', {})
    event = AccidentEvent.objects.create(
        journey=journey,
        event_type=event_type,
        latitude=lat, longitude=lng,
        raw_sensor=raw,
        **{k: v for k, v in kwargs.items() if v is not None},
    )
    _broadcast(journey, f'{event_type.lower().replace("_", ".")}.detected', {
        'event_id': str(event.id),
        'event_type': event_type,
        'severity': event.severity,
        'lat': lat, 'lng': lng,
    })
    return event


# ── confirmation countdown (Story 6-7) ────────────────────────────────────────

def _start_confirmation_countdown(journey, event):
    """Mark the event as a POSSIBLE_ACCIDENT and schedule auto-escalation."""
    from accident_detection.models import AccidentEvent
    from accident_detection.tasks import auto_escalate_accident

    event.event_type = AccidentEvent.EventType.POSSIBLE_ACCIDENT
    event.save(update_fields=['event_type'])

    _broadcast(journey, 'possible.accident', {
        'event_id': str(event.id),
        'severity': event.severity,
        'confirmation_timeout_s': CONFIRMATION_TIMEOUT_S(),
        'message': 'Possible accident detected. Please confirm your status.',
    })

    # Schedule auto-escalation after the confirmation window.
    result = auto_escalate_accident.apply_async(
        args=[str(event.id)],
        countdown=CONFIRMATION_TIMEOUT_S(),
    )
    event.countdown_task_id = result.id
    event.save(update_fields=['countdown_task_id'])


def confirm_accident(event, user, response: str) -> 'AccidentEvent':
    """Record the user's response to a possible-accident prompt (Story 6).

    response: 'SAFE' | 'NEEDS_HELP'
    """
    from accident_detection.models import AccidentEvent

    if event.confirmation_status not in (
        AccidentEvent.ConfirmationStatus.PENDING,
    ):
        return event  # already resolved

    event.confirmation_status = response  # 'SAFE' or 'NEEDS_HELP'
    event.confirmed_at = timezone.now()
    event.save(update_fields=['confirmation_status', 'confirmed_at'])

    if response == AccidentEvent.ConfirmationStatus.NEEDS_HELP:
        _escalate_accident(event)
    else:
        _broadcast(event.journey, 'possible.accident.resolved', {
            'event_id': str(event.id), 'response': 'SAFE',
        })

    return event


def auto_escalate_if_unconfirmed(event_id: str):
    """Called by the Celery task after the countdown expires (Story 7)."""
    from accident_detection.models import AccidentEvent
    try:
        event = AccidentEvent.objects.select_related('journey').get(id=event_id)
    except AccidentEvent.DoesNotExist:
        return

    if event.confirmation_status != AccidentEvent.ConfirmationStatus.PENDING:
        return  # already resolved by user

    event.confirmation_status = AccidentEvent.ConfirmationStatus.TIMED_OUT
    event.save(update_fields=['confirmation_status'])
    _escalate_accident(event)


def _escalate_accident(event) -> 'EmergencyEscalation':
    """Create an iSafePass incident for a confirmed or timed-out accident (Story 8)."""
    from accident_detection.models import AccidentEvent, EmergencyEscalation

    journey = event.journey
    loc = journey.last_location

    payload = {
        'journey_id': str(journey.id),
        'passenger_id': str(journey.passenger.pk),
        'participant_id': str(journey.driver.user.pk),
        'asset_id': str(journey.vehicle.pk),
        'event_type': event.event_type,
        'severity': event.severity,
        'confirmation_status': event.confirmation_status,
        'location': {
            'lat': event.latitude or (loc.latitude if loc else None),
            'lng': event.longitude or (loc.longitude if loc else None),
        },
        'sensor': {
            'acceleration_magnitude': event.acceleration_magnitude,
            'speed_before': event.speed_before,
            'speed_after': event.speed_after,
            'tilt_angle': event.tilt_angle,
        },
        'detected_at': str(event.detected_at),
    }

    escalation = EmergencyEscalation.objects.create(
        journey=journey,
        accident_event=event,
        escalation_type=EmergencyEscalation.EscalationType.ACCIDENT_INCIDENT,
        payload=payload,
    )
    _deliver_escalation(escalation)

    # Notify trusted contacts (Story 9).
    notify_emergency_contacts(journey, 'accident_detected', payload)
    return escalation


# ── manual SOS / panic (Stories 4-5) ──────────────────────────────────────────

def trigger_sos(journey, user, lat=None, lng=None, message='') -> 'SOSRequest':
    """Passenger-initiated SOS (Story 4)."""
    from accident_detection.models import SOSRequest
    return _create_sos(journey, user, SOSRequest.SOSType.PASSENGER_SOS, lat, lng, message)


def trigger_panic(journey, user, lat=None, lng=None, message='') -> 'SOSRequest':
    """Driver / rider panic button (Story 5)."""
    from accident_detection.models import SOSRequest
    return _create_sos(journey, user, SOSRequest.SOSType.DRIVER_PANIC, lat, lng, message)


def _create_sos(journey, user, sos_type, lat, lng, message) -> 'SOSRequest':
    from accident_detection.models import EmergencyEscalation, SOSRequest

    loc = journey.last_location
    sos = SOSRequest.objects.create(
        journey=journey, triggered_by=user, sos_type=sos_type,
        latitude=lat or (loc.latitude if loc else None),
        longitude=lng or (loc.longitude if loc else None),
        message=message,
    )

    _broadcast(journey, 'sos.triggered' if sos_type == SOSRequest.SOSType.PASSENGER_SOS else 'panic.triggered', {
        'sos_id': str(sos.id), 'sos_type': sos_type,
        'lat': sos.latitude, 'lng': sos.longitude,
        'message': message,
    })

    payload = {
        'journey_id': str(journey.id),
        'passenger_id': str(journey.passenger.pk),
        'participant_id': str(journey.driver.user.pk),
        'asset_id': str(journey.vehicle.pk),
        'sos_type': sos_type,
        'location': {'lat': sos.latitude, 'lng': sos.longitude},
        'message': message,
        'triggered_at': str(sos.triggered_at),
    }

    esc_type = (EmergencyEscalation.EscalationType.SOS
                if sos_type == SOSRequest.SOSType.PASSENGER_SOS
                else EmergencyEscalation.EscalationType.PANIC)

    escalation = EmergencyEscalation.objects.create(
        journey=journey, sos_request=sos,
        escalation_type=esc_type, payload=payload,
    )
    _deliver_escalation(escalation)

    # Notify recipients immediately (Story 9).
    notify_emergency_contacts(journey, 'sos_triggered', payload)
    return sos


# ── iSafePass delivery (Stories 8, 12) ────────────────────────────────────────

def _deliver_escalation(escalation) -> bool:
    """Attempt delivery to iSafePass, log the result, schedule retry on failure."""
    from integrations.services.isafepass_bridge import get_bridge, ISafePassUnavailable
    from accident_detection.models import DeliveryLog, EmergencyEscalation

    bridge = get_bridge()
    attempt = escalation.retry_count + 1
    start = time.monotonic()
    success = False
    http_status = None
    response_body = ''
    error = ''
    result = {}

    try:
        if not bridge.enabled:
            raise ISafePassUnavailable('iSafePass bridge not configured.')

        if escalation.escalation_type == EmergencyEscalation.EscalationType.ACCIDENT_INCIDENT:
            result = bridge.create_incident(escalation.payload)
            escalation.isafepass_incident_id = result.get('incident_id', '')
            _broadcast(escalation.journey, 'incident.created', result)
        else:
            result = bridge.trigger_sos(escalation.payload)
            escalation.isafepass_sos_id = result.get('sos_id', '')
            _broadcast(escalation.journey, 'incident.escalated', result)

        escalation.status = EmergencyEscalation.Status.DELIVERED
        escalation.response_data = result
        escalation.delivered_at = timezone.now()
        success = True

        if escalation.sos_request_id:
            from accident_detection.models import SOSRequest
            SOSRequest.objects.filter(id=escalation.sos_request_id).update(
                status=SOSRequest.Status.DELIVERED,
                isafepass_sos_id=escalation.isafepass_sos_id or result.get('sos_id', ''),
                delivered_at=timezone.now(),
                response_data=result,
            )

        if escalation.accident_event_id:
            from accident_detection.models import AccidentEvent
            AccidentEvent.objects.filter(id=escalation.accident_event_id).update(
                confirmation_status=AccidentEvent.ConfirmationStatus.ESCALATED,
                escalated_at=timezone.now(),
            )

    except ISafePassUnavailable as exc:
        error = str(exc)
        escalation.error_message = error
        escalation.status = EmergencyEscalation.Status.FAILED
        logger.warning('Emergency escalation %s failed: %s', escalation.id, error)

        if escalation.retry_count < MAX_RETRIES():
            escalation.status = EmergencyEscalation.Status.RETRYING
            delay = RETRY_DELAY_S() * (2 ** escalation.retry_count)
            escalation.next_retry_at = timezone.now() + timezone.timedelta(seconds=delay)
            from accident_detection.tasks import retry_escalation
            retry_escalation.apply_async(
                args=[str(escalation.id)], countdown=delay,
            )
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        escalation.retry_count = attempt
        escalation.save(update_fields=[
            'status', 'response_data', 'delivered_at', 'error_message',
            'retry_count', 'next_retry_at', 'isafepass_incident_id', 'isafepass_sos_id',
        ])
        DeliveryLog.objects.create(
            escalation=escalation,
            attempt_number=attempt,
            success=success,
            http_status=http_status,
            response_body=response_body[:4000],
            error=error,
            duration_ms=duration_ms,
        )

    return success


# ── emergency contact notifications (Story 9) ────────────────────────────────

def notify_emergency_contacts(journey, event_type: str, data: dict):
    """Fan-out emergency notifications to trusted contacts via sharing module."""
    try:
        from journeys.sharing import notify_recipients
        ws_event = {
            'accident_detected': 'journey.sos',
            'sos_triggered': 'journey.sos',
        }.get(event_type, 'journey.alert')
        notify_recipients(journey, ws_event, {
            'emergency': True,
            'event_type': event_type,
            'message': _emergency_message(event_type),
            **data,
        })
    except Exception as exc:
        logger.warning('notify_emergency_contacts failed: %s', exc)


def _emergency_message(event_type: str) -> str:
    return {
        'accident_detected': 'A possible accident has been detected on this journey.',
        'sos_triggered': 'An SOS has been triggered on this journey.',
    }.get(event_type, 'An emergency event has occurred on this journey.')


# ── emergency timeline (Story 11) ────────────────────────────────────────────

def get_emergency_timeline(journey) -> list:
    """Ordered list of all emergency events and escalations for a journey."""
    from accident_detection.models import AccidentEvent, SOSRequest, EmergencyEscalation

    timeline = []

    for e in AccidentEvent.objects.filter(journey=journey).order_by('detected_at'):
        timeline.append({
            'type': 'accident_event',
            'event_type': e.event_type,
            'severity': e.severity,
            'confirmation_status': e.confirmation_status,
            'detected_at': e.detected_at,
            'confirmed_at': e.confirmed_at,
            'escalated_at': e.escalated_at,
            'id': str(e.id),
        })

    for s in SOSRequest.objects.filter(journey=journey).order_by('triggered_at'):
        timeline.append({
            'type': 'sos_request',
            'sos_type': s.sos_type,
            'status': s.status,
            'triggered_at': s.triggered_at,
            'delivered_at': s.delivered_at,
            'isafepass_sos_id': s.isafepass_sos_id,
            'id': str(s.id),
        })

    for esc in EmergencyEscalation.objects.filter(journey=journey).order_by('created_at'):
        timeline.append({
            'type': 'escalation',
            'escalation_type': esc.escalation_type,
            'status': esc.status,
            'created_at': esc.created_at,
            'delivered_at': esc.delivered_at,
            'retry_count': esc.retry_count,
            'isafepass_incident_id': esc.isafepass_incident_id,
            'id': str(esc.id),
        })

    timeline.sort(key=lambda x: (
        x.get('detected_at') or x.get('triggered_at') or x.get('created_at')
    ))
    return timeline


# ── Channels helper ───────────────────────────────────────────────────────────

def _broadcast(journey, event_type: str, data: dict = None):
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(
            f'journey_{journey.id}',
            {'type': 'journey.event', 'event': event_type,
             'journey_id': str(journey.id), 'data': data or {}},
        )
    except Exception:
        pass
