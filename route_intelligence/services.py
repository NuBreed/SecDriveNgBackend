"""
Route Intelligence service layer.

Responsibilities
----------------
- Geometry helpers (haversine, bearing, distance-to-polyline).
- Planned route management (Story 1).
- Per-location analysis pipeline (Stories 2-7).
- Risk score computation (Story 8).
- Warning creation and broadcast (Story 9).
- iSafePass incident escalation (Stories 11-12).
"""
import logging
import math

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# ── configurable thresholds ────────────────────────────────────────────────────
_CFG = lambda key, default: getattr(settings, key, default)  # noqa: E731

DEVIATION_MINOR_M = lambda: _CFG('ROUTE_DEVIATION_MINOR_M', 200)
DEVIATION_MAJOR_M = lambda: _CFG('ROUTE_DEVIATION_MAJOR_M', 500)
DEVIATION_CRITICAL_M = lambda: _CFG('ROUTE_DEVIATION_CRITICAL_M', 1000)
WRONG_DIR_THRESHOLD = lambda: _CFG('WRONG_DIRECTION_THRESHOLD_DEG', 90)
STOP_SPEED_MS = lambda: _CFG('UNEXPECTED_STOP_SPEED_MS', 0.5)
STOP_DURATION_S = lambda: _CFG('UNEXPECTED_STOP_DURATION_S', 180)


# ── geometry helpers ──────────────────────────────────────────────────────────

def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the great-circle distance in metres between two lat/lng points."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(math.sqrt(min(1.0, a)))


def bearing(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the forward bearing (0-360°, clockwise from north) from p1 to p2."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlng = math.radians(lng2 - lng1)
    x = math.sin(dlng) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlng)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def angle_diff(a: float, b: float) -> float:
    """Shortest angular difference between two headings (0-180°)."""
    diff = abs(a - b) % 360
    return diff if diff <= 180 else 360 - diff


def _distance_point_to_segment(px, py, ax, ay, bx, by) -> float:
    """Cartesian distance from point P to segment AB (in same coordinate space)."""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def distance_to_route(lat: float, lng: float, waypoints: list) -> float:
    """Minimum distance (metres) from (lat, lng) to any segment of the polyline.

    Falls back to distance-to-single-point when only one waypoint is provided.
    """
    if not waypoints:
        return 0.0
    if len(waypoints) == 1:
        return haversine(lat, lng, waypoints[0]['lat'], waypoints[0]['lng'])

    # Use a flat-earth approximation in degrees for segment math; convert to metres
    # at the end using a per-latitude scale factor. Accurate enough for < 5 km routes.
    lat_scale = 111_320.0  # metres per degree latitude
    lng_scale = 111_320.0 * math.cos(math.radians(lat))

    px = (lng - waypoints[0]['lng']) * lng_scale
    py = (lat - waypoints[0]['lat']) * lat_scale

    min_dist = float('inf')
    for i in range(len(waypoints) - 1):
        ax = (waypoints[i]['lng'] - waypoints[0]['lng']) * lng_scale
        ay = (waypoints[i]['lat'] - waypoints[0]['lat']) * lat_scale
        bx = (waypoints[i + 1]['lng'] - waypoints[0]['lng']) * lng_scale
        by = (waypoints[i + 1]['lat'] - waypoints[0]['lat']) * lat_scale
        d = _distance_point_to_segment(px, py, ax, ay, bx, by)
        if d < min_dist:
            min_dist = d
    return min_dist


# ── planned route management (Story 1) ────────────────────────────────────────

def set_planned_route(journey, waypoints: list,
                      expected_duration_s: int = None,
                      expected_distance_m: float = None):
    """Create or replace the planned route for a journey."""
    from route_intelligence.models import PlannedRoute
    PlannedRoute.objects.update_or_create(
        journey=journey,
        defaults={
            'waypoints': waypoints,
            'expected_duration_s': expected_duration_s,
            'expected_distance_m': expected_distance_m,
            'status': PlannedRoute.Status.ACTIVE,
        },
    )


# ── per-location analysis pipeline (Story 2) ──────────────────────────────────

def analyze_location(journey, location):
    """Run the full risk analysis pipeline for a single GPS location.

    Called after every successful ``record_location`` write.
    """
    events = []

    # Story 3: route deviation.
    deviation = _check_route_deviation(journey, location)
    if deviation:
        events.append(('route.deviation.detected', {
            'deviation_id': str(deviation.id),
            'type': deviation.deviation_type,
            'severity': deviation.severity,
            'distance_m': deviation.distance_from_route_m,
        }))

    # Story 4: wrong direction.
    wrong_dir = _check_wrong_direction(journey, location)
    if wrong_dir:
        events.append(('wrong.direction.detected', {
            'deviation_id': str(wrong_dir.id),
            'heading_error_deg': wrong_dir.heading_error_deg,
        }))

    # Story 5: unexpected stop.
    stop = _check_unexpected_stop(journey, location)
    if stop:
        events.append(('unexpected.stop.detected', {
            'stop_id': str(stop.id),
            'duration_s': stop.duration_s,
        }))

    # Story 8: risk score.
    risk = _compute_risk(journey)
    events.append(('journey.risk.updated', {
        'score': risk.score,
        'level': risk.level,
        'factors': risk.factors,
    }))

    # Story 9: emit warnings for new events.
    for event_type, data in events:
        _emit_warning(journey, event_type, data)

    # Stories 11-12: recommend / auto-create incident.
    if risk.level == 'CRITICAL' and not risk.incident_created:
        _recommend_or_escalate(journey, risk)

    # Broadcast all events.
    for event_type, data in events:
        _broadcast(journey, event_type, data)


# ── deviation detection (Story 3) ─────────────────────────────────────────────

def _check_route_deviation(journey, location):
    from route_intelligence.models import PlannedRoute, RouteDeviation
    try:
        plan = journey.planned_route
    except PlannedRoute.DoesNotExist:
        return None

    if not plan.waypoints:
        return None

    dist = distance_to_route(location.latitude, location.longitude, plan.waypoints)

    if dist < DEVIATION_MINOR_M():
        # Back on route — resolve any open deviations and restore plan status.
        journey.deviations.filter(
            deviation_type=RouteDeviation.DeviationType.ROUTE_DEVIATION,
            is_resolved=False,
        ).update(is_resolved=True, resolved_at=timezone.now())
        if plan.status == PlannedRoute.Status.DEVIATED:
            plan.status = PlannedRoute.Status.ACTIVE
            plan.save(update_fields=['status'])
        return None

    # Only create new deviations while the route is formally active.
    if plan.status not in (PlannedRoute.Status.ACTIVE, PlannedRoute.Status.DEVIATED):
        return None

    # Determine severity.
    if dist >= DEVIATION_CRITICAL_M():
        severity = RouteDeviation.Severity.CRITICAL
    elif dist >= DEVIATION_MAJOR_M():
        severity = RouteDeviation.Severity.HIGH
    else:
        severity = RouteDeviation.Severity.MEDIUM

    # Don't duplicate if an unresolved deviation of same severity already exists.
    if journey.deviations.filter(
        deviation_type=RouteDeviation.DeviationType.ROUTE_DEVIATION,
        severity=severity, is_resolved=False,
    ).exists():
        return None

    deviation = RouteDeviation.objects.create(
        journey=journey,
        deviation_type=RouteDeviation.DeviationType.ROUTE_DEVIATION,
        severity=severity,
        latitude=location.latitude,
        longitude=location.longitude,
        distance_from_route_m=dist,
    )

    # Update plan status.
    if severity in (RouteDeviation.Severity.HIGH, RouteDeviation.Severity.CRITICAL):
        plan.status = PlannedRoute.Status.DEVIATED
        plan.save(update_fields=['status'])

    return deviation


# ── wrong direction detection (Story 4) ───────────────────────────────────────

def _check_wrong_direction(journey, location):
    from route_intelligence.models import RouteDeviation

    if not (journey.destination_lat and journey.destination_lng):
        return None
    if location.heading is None:
        return None

    dest_bearing = bearing(
        location.latitude, location.longitude,
        journey.destination_lat, journey.destination_lng,
    )
    error = angle_diff(location.heading, dest_bearing)

    threshold = WRONG_DIR_THRESHOLD()
    if error < threshold:
        # Heading is acceptable — resolve open wrong-direction deviations.
        journey.deviations.filter(
            deviation_type=RouteDeviation.DeviationType.WRONG_DIRECTION,
            is_resolved=False,
        ).update(is_resolved=True, resolved_at=timezone.now())
        return None

    # Determine severity from the heading error magnitude.
    if error >= 150:
        severity = RouteDeviation.Severity.CRITICAL
    elif error >= 120:
        severity = RouteDeviation.Severity.HIGH
    else:
        severity = RouteDeviation.Severity.MEDIUM

    if journey.deviations.filter(
        deviation_type=RouteDeviation.DeviationType.WRONG_DIRECTION,
        severity=severity, is_resolved=False,
    ).exists():
        return None

    return RouteDeviation.objects.create(
        journey=journey,
        deviation_type=RouteDeviation.DeviationType.WRONG_DIRECTION,
        severity=severity,
        latitude=location.latitude,
        longitude=location.longitude,
        heading_error_deg=error,
        metadata={'heading': location.heading, 'destination_bearing': dest_bearing},
    )


# ── unexpected stop detection (Story 5) ───────────────────────────────────────

def _check_unexpected_stop(journey, location):
    from route_intelligence.models import UnexpectedStop

    speed = location.speed or 0.0  # m/s
    stopped = speed <= STOP_SPEED_MS()

    # Close any open stop that the vehicle has resumed from.
    open_stop = journey.unexpected_stops.filter(ended_at__isnull=True).first()

    if open_stop and not stopped:
        open_stop.ended_at = location.timestamp
        open_stop.duration_s = int(
            (location.timestamp - open_stop.started_at).total_seconds()
        )
        open_stop.is_resolved = True
        open_stop.resolved_at = location.timestamp
        open_stop.save(update_fields=['ended_at', 'duration_s', 'is_resolved', 'resolved_at'])
        return None

    if not stopped:
        return None

    # Vehicle is currently stopped.
    if open_stop:
        # Already tracking this stop — check if threshold has been reached.
        duration = (location.timestamp - open_stop.started_at).total_seconds()
        if duration >= STOP_DURATION_S() and not open_stop.is_resolved:
            open_stop.duration_s = int(duration)
            open_stop.save(update_fields=['duration_s'])
            return open_stop
        return None

    # New stop detected — create the record and wait for the threshold.
    return UnexpectedStop.objects.create(
        journey=journey,
        latitude=location.latitude,
        longitude=location.longitude,
        started_at=location.timestamp or timezone.now(),
    )


# ── risk scoring (Story 8) ────────────────────────────────────────────────────

_DEVIATION_SCORE = {
    'LOW': 10, 'MEDIUM': 20, 'HIGH': 35, 'CRITICAL': 50,
}

_LEVEL_THRESHOLDS = [
    (80, 'CRITICAL'),
    (60, 'HIGH'),
    (30, 'MEDIUM'),
    (0, 'LOW'),
]


def _compute_risk(journey):
    from route_intelligence.models import JourneyRisk, RouteDeviation

    risk, _ = JourneyRisk.objects.get_or_create(journey=journey)

    factors = {}

    # Route deviations.
    deviations = list(journey.deviations.filter(is_resolved=False))
    dev_score = 0
    for d in deviations:
        dev_score = max(dev_score, _DEVIATION_SCORE.get(d.severity, 0))
    factors['route_deviation'] = dev_score

    # Wrong direction: captured via deviations table with WRONG_DIRECTION type.
    wd_deviations = [d for d in deviations
                     if d.deviation_type == RouteDeviation.DeviationType.WRONG_DIRECTION]
    factors['wrong_direction'] = 25 if wd_deviations else 0

    # Unexpected stops.
    active_stops = journey.unexpected_stops.filter(is_resolved=False, ended_at__isnull=True)
    factors['unexpected_stop'] = min(30, 15 * active_stops.count())

    total = min(100, sum(factors.values()))
    level = next(level for threshold, level in _LEVEL_THRESHOLDS if total >= threshold)

    risk.score = total
    risk.level = level
    risk.factors = factors
    risk.save(update_fields=['score', 'level', 'factors'])
    return risk


# ── warning generation (Story 9) ──────────────────────────────────────────────

_WARNING_TEMPLATES = {
    'route.deviation.detected': {
        'type': 'ROUTE_DEVIATION',
        'title': 'Route Deviation Detected',
        'message': 'Your journey is moving away from the expected route.',
        'severity': 'WARNING',
    },
    'wrong.direction.detected': {
        'type': 'WRONG_DIRECTION',
        'title': 'Wrong Direction Detected',
        'message': 'The vehicle appears to be travelling away from the destination.',
        'severity': 'DANGER',
    },
    'unexpected.stop.detected': {
        'type': 'UNEXPECTED_STOP',
        'title': 'Unexpected Stop Detected',
        'message': 'The vehicle has stopped for an unusual amount of time.',
        'severity': 'WARNING',
    },
    'journey.risk.updated': None,  # risk updates don't directly produce a warning
}


def _emit_warning(journey, event_type, data):
    from route_intelligence.models import JourneyWarning

    tpl = _WARNING_TEMPLATES.get(event_type)
    if not tpl:
        return None

    # High-risk severity escalation.
    risk_level = data.get('level', '')
    if risk_level in ('HIGH', 'CRITICAL'):
        tpl = tpl.copy()
        tpl['severity'] = 'CRITICAL' if risk_level == 'CRITICAL' else 'DANGER'

    return JourneyWarning.objects.create(
        journey=journey,
        warning_type=tpl['type'],
        severity=tpl['severity'],
        title=tpl['title'],
        message=tpl['message'],
        metadata=data,
    )


def create_high_risk_warning(journey, risk):
    """Create a HIGH_RISK warning when the risk level crosses HIGH/CRITICAL."""
    from route_intelligence.models import JourneyWarning
    severity_map = {'HIGH': 'DANGER', 'CRITICAL': 'CRITICAL'}
    sev = severity_map.get(risk.level)
    if not sev:
        return None
    # Don't duplicate.
    if journey.warnings.filter(warning_type='HIGH_RISK', is_resolved=False).exists():
        return None
    return JourneyWarning.objects.create(
        journey=journey,
        warning_type=JourneyWarning.WarningType.HIGH_RISK,
        severity=sev,
        title=f'Risk Level: {risk.level}',
        message=f'The journey risk score has reached {risk.score:.0f}/100 ({risk.level}).',
        metadata={'score': risk.score, 'factors': risk.factors},
    )


# ── escalation (Stories 11-12) ────────────────────────────────────────────────

def _recommend_or_escalate(journey, risk):
    from route_intelligence.models import JourneyWarning
    from django.conf import settings

    auto_escalate = getattr(settings, 'ROUTE_INTELLIGENCE_AUTO_ESCALATE', False)

    if auto_escalate:
        result = escalate_to_isafepass(journey, reason='Auto-escalated: critical risk score.')
        if result:
            JourneyWarning.objects.create(
                journey=journey,
                warning_type=JourneyWarning.WarningType.INCIDENT_CREATED,
                severity=JourneyWarning.Severity.CRITICAL,
                title='Incident Created',
                message='A safety incident has been created in iSafePass for this journey.',
                metadata={'incident_id': result.get('incident_id', '')},
            )
    else:
        # Only recommend — passenger must manually escalate.
        if not journey.warnings.filter(
            warning_type=JourneyWarning.WarningType.INCIDENT_RECOMMENDED,
            is_resolved=False,
        ).exists():
            JourneyWarning.objects.create(
                journey=journey,
                warning_type=JourneyWarning.WarningType.INCIDENT_RECOMMENDED,
                severity=JourneyWarning.Severity.CRITICAL,
                title='Create Incident',
                message='Risk thresholds have been exceeded. Consider creating a safety incident.',
                metadata={'score': risk.score, 'level': risk.level},
            )


def escalate_to_isafepass(journey, reason: str = '') -> dict | None:
    """POST an incident to iSafePass and record the result on JourneyRisk.

    Returns the response dict on success, or None if the bridge is unavailable.
    """
    from integrations.services.isafepass_bridge import get_bridge, ISafePassUnavailable

    bridge = get_bridge()
    if not bridge.enabled:
        logger.info('iSafePass bridge not configured — skipping incident creation for %s', journey.id)
        return None

    driver = journey.driver
    vehicle = journey.vehicle
    risk = getattr(journey, 'risk', None)

    payload = {
        'journey_id': str(journey.id),
        'passenger_id': str(journey.passenger.pk),
        'participant_id': str(driver.user.pk),
        'asset_id': str(vehicle.pk),
        'reason': reason or 'Journey risk threshold exceeded.',
        'risk_score': risk.score if risk else None,
        'risk_level': risk.level if risk else None,
        'origin': {'lat': journey.origin_lat, 'lng': journey.origin_lng},
        'destination': {'lat': journey.destination_lat, 'lng': journey.destination_lng},
    }

    try:
        result = bridge.create_incident(payload)
        from route_intelligence.models import JourneyRisk
        jr, _ = JourneyRisk.objects.get_or_create(journey=journey)
        jr.incident_created = True
        jr.incident_id = result.get('incident_id', '')
        jr.save(update_fields=['incident_created', 'incident_id'])
        _broadcast(journey, 'incident.created', result)
        return result
    except ISafePassUnavailable as exc:
        logger.warning('Could not create iSafePass incident for journey %s: %s', journey.id, exc)
        return None


# ── Channels broadcast helper ─────────────────────────────────────────────────

def _broadcast(journey, event_type: str, data: dict = None):
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
                'data': data or {},
            },
        )
    except Exception:
        pass


# ── Sharing notifications (Story 10) ─────────────────────────────────────────

def notify_recipients_of_risk(journey, event_type: str, data: dict):
    """Fan-out risk/warning events to journey share recipients."""
    from journeys.sharing import notify_recipients
    notify_recipients(journey, event_type, data)


# ── Pre-ride Route Safety Check (via iSafePass Partner API) ──────────────────

def check_route_safety(place_id: str, destination: str) -> dict:
    """
    Return a safety report for a destination by:
    1. Resolving place_id → lat/lng via Google Places Details (places app).
    2. Calling iSafePass /api/v1/safety/route-intelligence/ for real corridor safety.
    3. Calling iSafePass /api/v1/safety/route-alternatives/ for ranked safe routes.
    4. Normalising both responses into the shape the Flutter app expects.

    Falls back to a safe-default response when iSafePass is not configured.
    """
    from places.services import place_details
    from integrations.services.isafepass_bridge import ISafePassBridge, ISafePassUnavailable

    # ── 1. Resolve coordinates ────────────────────────────────────────────────
    origin_lat = getattr(settings, 'ROUTE_CHECK_DEFAULT_LAT', 6.5244)
    origin_lng = getattr(settings, 'ROUTE_CHECK_DEFAULT_LNG', 3.3792)
    dest_lat, dest_lng = origin_lat, origin_lng

    details = place_details(place_id)
    if details:
        # New Places API v1 shape: {"location": {"latitude": ..., "longitude": ...}}
        loc = details.get('location') or {}
        if loc.get('latitude'):
            dest_lat = float(loc['latitude'])
            dest_lng = float(loc['longitude'])
        # Legacy shape: {"geometry": {"location": {"lat": ..., "lng": ...}}}
        elif details.get('geometry', {}).get('location'):
            loc = details['geometry']['location']
            dest_lat = float(loc['lat'])
            dest_lng = float(loc['lng'])

    payload = {
        'origin_latitude':        origin_lat,
        'origin_longitude':       origin_lng,
        'destination_latitude':   dest_lat,
        'destination_longitude':  dest_lng,
    }

    # ── 2 & 3. Call iSafePass partner API ─────────────────────────────────────
    bridge = ISafePassBridge()
    try:
        safety_data = bridge._post('/api/v1/safety/route-intelligence/', payload)
        alt_data    = bridge._post('/api/v1/safety/route-alternatives/', payload)
    except ISafePassUnavailable:
        logger.warning('iSafePass not configured — returning default route safety response.')
        return _fallback_report(destination)
    except Exception as exc:
        logger.exception('iSafePass route-safety call failed: %s', exc)
        return _fallback_report(destination)

    # ── 4. Normalise ──────────────────────────────────────────────────────────
    raw_score    = safety_data.get('safety_score', 80)
    risk_level   = safety_data.get('risk_level', 'low')
    safety_level = _risk_level_to_label(risk_level)
    safety_score = int(raw_score)

    travel_advice = safety_data.get('travel_advice', {})
    summary = travel_advice.get('message') or _default_summary(safety_level, destination)

    # ── Risks with counts from statistics + named zones/alerts ───────────────
    stats = safety_data.get('statistics', {})
    risks: list[dict] = []

    _risk_labels = [
        ('incidents',       'Incidents'),
        ('hotspots',        'Hotspots'),
        ('threat_zones',    'Threat Zones'),
        ('alerts',          'Active Alerts'),
        ('missing_persons', 'Missing Person Cases'),
    ]
    for key, label in _risk_labels:
        count = stats.get(key, 0)
        if count:
            risks.append({'label': label, 'count': count})

    for zone in safety_data.get('threat_zones_crossed', []):
        name = zone.get('name', 'Unknown zone')
        inc  = zone.get('active_incident_count', 0)
        risks.append({'label': f'Threat zone: {name}', 'count': inc})

    for alert in safety_data.get('active_alerts', []):
        risks.append({'label': alert.get('title', 'Active alert'), 'count': 1})

    # ── Recommendations from travel_advice status ─────────────────────────────
    advice_status = travel_advice.get('status', 'safe')
    recommendations = _recommendations_for(advice_status, alt_data)

    # ── Alternatives from ranked routes (skip rank 1 = direct route) ─────────
    alternatives: list[dict] = []
    for route in alt_data.get('route_rankings', [])[1:4]:
        alt_score = int(route.get('safety_score', 0))
        alternatives.append({
            'name':         route.get('route_name', 'Alternative').replace('_', ' ').title(),
            'description':  route.get('travel_advice', {}).get('message', ''),
            'safety_level': _risk_level_to_label(route.get('risk_level', 'low')),
            'safety_score': alt_score,
        })

    return {
        'destination':       destination,
        'safety_level':      safety_level,
        'safety_score':      safety_score,
        'summary':           summary,
        'risks':             risks[:8],
        'recommendations':   recommendations,
        'alternatives':      alternatives,
    }


def _risk_level_to_label(risk_level: str) -> str:
    """Map iSafePass risk levels to Flutter app safety labels."""
    mapping = {
        'low':      'safe',
        'medium':   'moderate',
        'moderate': 'moderate',
        'risky':    'moderate',
        'high':     'dangerous',
        'dangerous':'dangerous',
        'critical': 'dangerous',
    }
    return mapping.get(risk_level.lower(), 'safe')


def _default_summary(safety_level: str, destination: str) -> str:
    return {
        'safe':      f'{destination} is generally considered safe for travel.',
        'moderate':  f'Exercise caution on your way to {destination}. Some risk factors noted.',
        'dangerous': f'High risk area detected near {destination}. Consider alternatives or travel in daylight.',
    }.get(safety_level, '')


def _recommendations_for(advice_status: str, alt_data: dict) -> list[str]:
    base = {
        'safe': [
            'Route looks clear — proceed normally.',
            'Stay alert and keep emergency contacts informed.',
        ],
        'caution': [
            'Share your live location with a trusted contact before departing.',
            'Travel during daylight hours where possible.',
            'Keep your phone charged and accessible.',
            'Consider one of the safer alternative routes below.',
        ],
        'high_caution': [
            'Avoid travelling alone on this route.',
            'Inform someone of your departure time and expected arrival.',
            'Use a safer alternative route if available.',
            'Keep doors locked and avoid stopping in unfamiliar areas.',
        ],
        'avoid': [
            'Avoid this route — high-risk conditions detected.',
            'Use one of the recommended alternative routes.',
            'If travel is unavoidable, go in a group during daylight only.',
            'Alert your emergency contacts before departing.',
        ],
    }.get(advice_status, ['Proceed with normal caution.'])

    # Append the top-ranked safe alternative as a specific recommendation
    for route in alt_data.get('route_rankings', []):
        if route.get('recommended') and route.get('route_name') != 'direct':
            name = route['route_name'].replace('_', ' ').title()
            base = [r for r in base if 'alternative' not in r.lower()]
            base.append(f'Recommended alternative: {name} (score {int(route.get("safety_score", 0))})')
            break

    return base


def _fallback_report(destination: str) -> dict:
    return {
        'destination':       destination,
        'safety_level':      'safe',
        'safety_score':      80,
        'summary':           f'Safety data temporarily unavailable for {destination}. Proceed with normal caution.',
        'risks':             [],
        'recommendations':   ['Proceed with normal caution.'],
        'alternatives': [],
    }
