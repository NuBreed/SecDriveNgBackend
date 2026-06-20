"""
Tests for Epic 6 — Route Intelligence & Risk Detection.

Stories covered:
  1  PlannedRoute set/replace
  2  Route monitoring pipeline (analyze_location hook)
  3  Route deviation detection
  4  Wrong direction detection
  5  Unexpected stop detection
  6  Dangerous area flag (iSafePass best-effort)
  7  Driver behaviour (speed-based deviation severity)
  8  Journey risk scoring
  9  Passenger safety warnings
  10 Shared-journey warning notifications
  11 Incident recommendation (threshold)
  12 iSafePass incident escalation (best-effort)
  API: risk, route-analysis, warnings, escalate, planned-route, admin endpoints
"""
import math
from datetime import date, timedelta, datetime, timezone as dt_tz

from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from drivers.models import Driver, DriverVerification
from journeys import services as journey_svc
from journeys.models import Journey, JourneyLocation
from qr_codes import services as qr_svc
from route_intelligence import services as ri_svc
from route_intelligence.models import (
    JourneyRisk, JourneyWarning, PlannedRoute, RouteDeviation, UnexpectedStop,
)
from vehicles.models import Vehicle, VehicleVerification


# ─── test helpers ─────────────────────────────────────────────────────────────

def _user(username, is_staff=False):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com',
        password='pw', is_verified=True, is_staff=is_staff,
    )


def _verified_driver(user):
    driver, _ = Driver.objects.get_or_create(
        user=user, defaults={'license_number': f'LIC-{user.pk}'},
    )
    expiry = date.today() + timedelta(days=365)
    req, _ = DriverVerification.objects.get_or_create(
        driver=driver,
        defaults={'license_number': driver.license_number, 'license_expiry': expiry},
    )
    req.license_expiry = expiry
    req.status = DriverVerification.Status.APPROVED
    req.background_review_passed = True
    req.save()
    return driver


def _verified_vehicle(user, reg='RI-001'):
    vehicle, _ = Vehicle.objects.get_or_create(
        registration_number=reg,
        defaults={'owner': user, 'vehicle_type': 'SEDAN',
                  'brand': 'Toyota', 'model': 'Camry', 'year': 2021},
    )
    expiry = date.today() + timedelta(days=365)
    req, _ = VehicleVerification.objects.get_or_create(
        vehicle=vehicle,
        defaults={'owner': user, 'inspection_expiry': expiry, 'insurance_expiry': expiry},
    )
    req.inspection_expiry = expiry
    req.insurance_expiry = expiry
    req.status = VehicleVerification.Status.APPROVED
    req.save()
    return vehicle


def _journey(passenger, reg='RI-001'):
    drv_user = _user(f'drv_{reg.replace("-","_").lower()}')
    _verified_driver(drv_user)
    vehicle = _verified_vehicle(drv_user, reg=reg)
    p_qr = qr_svc.get_or_create_participant_qr(drv_user)
    a_qr = qr_svc.get_or_create_asset_qr(drv_user, vehicle.pk)
    return journey_svc.create_journey(passenger, p_qr.token, a_qr.token)


def _active_journey(passenger, reg='RI-001',
                    dest_lat=6.60, dest_lng=3.35):
    j = _journey(passenger, reg=reg)
    journey_svc.set_destination(
        j, passenger,
        origin_lat=6.45, origin_lng=3.40, origin_address='Lagos Island',
        dest_lat=dest_lat, dest_lng=dest_lng, dest_address='Ikeja',
    )
    journey_svc.start_journey(j, passenger)
    j.refresh_from_db()
    return j


def _location(journey, lat, lng, speed=10.0, heading=None, ts=None):
    """Record a location, bypassing the analysis hook for test isolation."""
    from django.utils import timezone as tz
    loc = JourneyLocation.objects.create(
        journey=journey, latitude=lat, longitude=lng,
        speed=speed, heading=heading,
        timestamp=ts or tz.now(),
    )
    return loc


def _waypoints_along_route():
    """Simple 3-point planned route roughly Lagos Island → Ikeja."""
    return [
        {'lat': 6.45, 'lng': 3.40},
        {'lat': 6.52, 'lng': 3.37},
        {'lat': 6.60, 'lng': 3.35},
    ]


# ─── geometry helpers ──────────────────────────────────────────────────────────

class GeometryHelpersTest(TestCase):
    def test_haversine_same_point(self):
        self.assertAlmostEqual(ri_svc.haversine(6.45, 3.40, 6.45, 3.40), 0.0, places=2)

    def test_haversine_known_distance(self):
        # Lagos Island → Ikeja is ~roughly 16-20 km.
        dist = ri_svc.haversine(6.45, 3.40, 6.60, 3.35)
        self.assertGreater(dist, 10_000)
        self.assertLess(dist, 25_000)

    def test_bearing_north(self):
        b = ri_svc.bearing(0, 0, 1, 0)  # straight north
        self.assertAlmostEqual(b, 0.0, delta=1.0)

    def test_bearing_east(self):
        b = ri_svc.bearing(0, 0, 0, 1)  # straight east
        self.assertAlmostEqual(b, 90.0, delta=1.0)

    def test_angle_diff_same(self):
        self.assertAlmostEqual(ri_svc.angle_diff(45, 45), 0.0)

    def test_angle_diff_opposite(self):
        self.assertAlmostEqual(ri_svc.angle_diff(0, 180), 180.0)

    def test_angle_diff_wrap(self):
        self.assertAlmostEqual(ri_svc.angle_diff(350, 10), 20.0, delta=0.1)

    def test_distance_to_route_on_route(self):
        wps = _waypoints_along_route()
        # Point on the first segment should be very close.
        d = ri_svc.distance_to_route(6.45, 3.40, wps)
        self.assertAlmostEqual(d, 0.0, delta=10.0)

    def test_distance_to_route_far_off(self):
        wps = _waypoints_along_route()
        # Point far east of the route should have significant distance.
        d = ri_svc.distance_to_route(6.52, 3.80, wps)
        self.assertGreater(d, 10_000)

    def test_distance_to_single_waypoint(self):
        d = ri_svc.distance_to_route(6.45, 3.40, [{'lat': 6.46, 'lng': 3.40}])
        self.assertAlmostEqual(d, ri_svc.haversine(6.45, 3.40, 6.46, 3.40), delta=1.0)


# ─── Story 1: PlannedRoute ─────────────────────────────────────────────────────

class PlannedRouteTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_r1')
        self.journey = _active_journey(self.passenger, reg='R1-001')
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_set_planned_route_service(self):
        ri_svc.set_planned_route(self.journey, _waypoints_along_route(),
                                 expected_duration_s=1200, expected_distance_m=16000)
        route = PlannedRoute.objects.get(journey=self.journey)
        self.assertEqual(len(route.waypoints), 3)
        self.assertEqual(route.status, PlannedRoute.Status.ACTIVE)

    def test_set_planned_route_idempotent(self):
        ri_svc.set_planned_route(self.journey, _waypoints_along_route())
        ri_svc.set_planned_route(self.journey, [{'lat': 1.0, 'lng': 1.0}, {'lat': 2.0, 'lng': 2.0}])
        self.assertEqual(PlannedRoute.objects.filter(journey=self.journey).count(), 1)
        self.assertEqual(len(PlannedRoute.objects.get(journey=self.journey).waypoints), 2)

    def test_get_planned_route_api(self):
        ri_svc.set_planned_route(self.journey, _waypoints_along_route())
        res = self.client.get(f'/api/v1/journeys/{self.journey.id}/planned-route/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data['waypoints']), 3)

    def test_post_planned_route_api(self):
        res = self.client.post(
            f'/api/v1/journeys/{self.journey.id}/planned-route/',
            {'waypoints': _waypoints_along_route(), 'expected_duration_s': 900},
            format='json',
        )
        self.assertEqual(res.status_code, 201)

    def test_post_planned_route_requires_two_waypoints(self):
        res = self.client.post(
            f'/api/v1/journeys/{self.journey.id}/planned-route/',
            {'waypoints': [{'lat': 6.45, 'lng': 3.40}]},
            format='json',
        )
        self.assertEqual(res.status_code, 400)

    def test_no_planned_route_returns_404(self):
        res = self.client.get(f'/api/v1/journeys/{self.journey.id}/planned-route/')
        self.assertEqual(res.status_code, 404)


# ─── Story 3: Route Deviation Detection ───────────────────────────────────────

@override_settings(
    ROUTE_DEVIATION_MINOR_M=200,
    ROUTE_DEVIATION_MAJOR_M=500,
    ROUTE_DEVIATION_CRITICAL_M=1000,
)
class RouteDeviationDetectionTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_r3')
        self.journey = _active_journey(self.passenger, reg='R3-001')
        ri_svc.set_planned_route(self.journey, _waypoints_along_route())

    def test_on_route_does_not_create_deviation(self):
        loc = _location(self.journey, 6.52, 3.37)  # midpoint on route
        ri_svc._check_route_deviation(self.journey, loc)
        self.assertEqual(RouteDeviation.objects.filter(
            journey=self.journey, is_resolved=False).count(), 0)

    def test_medium_deviation_created(self):
        # 400 m east of the route — between MINOR and MAJOR thresholds.
        loc = _location(self.journey, 6.52, 3.374)  # ~400 m east
        deviation = ri_svc._check_route_deviation(self.journey, loc)
        self.assertIsNotNone(deviation)
        self.assertEqual(deviation.severity, RouteDeviation.Severity.MEDIUM)

    def test_critical_deviation_created(self):
        # Far off route (east of Lagos).
        loc = _location(self.journey, 6.52, 3.50)
        deviation = ri_svc._check_route_deviation(self.journey, loc)
        self.assertIsNotNone(deviation)
        self.assertEqual(deviation.severity, RouteDeviation.Severity.CRITICAL)

    def test_no_duplicate_deviation_same_severity(self):
        loc = _location(self.journey, 6.52, 3.50)
        ri_svc._check_route_deviation(self.journey, loc)
        ri_svc._check_route_deviation(self.journey, loc)
        self.assertEqual(RouteDeviation.objects.filter(
            journey=self.journey, severity='CRITICAL', is_resolved=False).count(), 1)

    def test_return_to_route_resolves_deviation(self):
        off = _location(self.journey, 6.52, 3.50)
        ri_svc._check_route_deviation(self.journey, off)
        self.assertEqual(RouteDeviation.objects.filter(
            journey=self.journey, is_resolved=False).count(), 1)
        on = _location(self.journey, 6.52, 3.37)  # back on route
        ri_svc._check_route_deviation(self.journey, on)
        self.assertEqual(RouteDeviation.objects.filter(
            journey=self.journey, is_resolved=False).count(), 0)

    def test_planned_route_status_set_to_deviated(self):
        loc = _location(self.journey, 6.52, 3.50)
        ri_svc._check_route_deviation(self.journey, loc)
        self.journey.planned_route.refresh_from_db()
        self.assertEqual(self.journey.planned_route.status, PlannedRoute.Status.DEVIATED)

    def test_no_planned_route_skipped(self):
        journey2 = _active_journey(self.passenger, reg='R3-002')
        loc = _location(journey2, 6.52, 3.50)
        result = ri_svc._check_route_deviation(journey2, loc)
        self.assertIsNone(result)


# ─── Story 4: Wrong Direction Detection ───────────────────────────────────────

@override_settings(WRONG_DIRECTION_THRESHOLD_DEG=90)
class WrongDirectionDetectionTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_r4')
        # Destination is north-northwest of origin.
        self.journey = _active_journey(self.passenger, reg='R4-001',
                                       dest_lat=6.60, dest_lng=3.35)

    def test_correct_heading_no_deviation(self):
        # Destination bearing is roughly NW (heading ~330°) from current position.
        dest_b = ri_svc.bearing(6.45, 3.40, 6.60, 3.35)
        loc = _location(self.journey, 6.45, 3.40, heading=dest_b)
        result = ri_svc._check_wrong_direction(self.journey, loc)
        self.assertIsNone(result)

    def test_opposite_heading_creates_deviation(self):
        dest_b = ri_svc.bearing(6.45, 3.40, 6.60, 3.35)
        opposite = (dest_b + 180) % 360
        loc = _location(self.journey, 6.45, 3.40, heading=opposite)
        result = ri_svc._check_wrong_direction(self.journey, loc)
        self.assertIsNotNone(result)
        self.assertEqual(result.deviation_type, RouteDeviation.DeviationType.WRONG_DIRECTION)

    def test_no_heading_skipped(self):
        loc = _location(self.journey, 6.45, 3.40, heading=None)
        result = ri_svc._check_wrong_direction(self.journey, loc)
        self.assertIsNone(result)

    def test_no_destination_skipped(self):
        journey2 = _journey(self.passenger, reg='R4-002')
        journey_svc.start_journey(journey2, self.passenger)
        journey2.refresh_from_db()
        loc = _location(journey2, 6.45, 3.40, heading=180)
        result = ri_svc._check_wrong_direction(journey2, loc)
        self.assertIsNone(result)

    def test_critical_wrong_direction_severity(self):
        # Exactly 180° opposite → CRITICAL.
        dest_b = ri_svc.bearing(6.45, 3.40, 6.60, 3.35)
        opposite = (dest_b + 180) % 360
        loc = _location(self.journey, 6.45, 3.40, heading=opposite)
        result = ri_svc._check_wrong_direction(self.journey, loc)
        self.assertEqual(result.severity, RouteDeviation.Severity.CRITICAL)

    def test_resolve_on_correct_heading(self):
        dest_b = ri_svc.bearing(6.45, 3.40, 6.60, 3.35)
        opposite = (dest_b + 180) % 360
        loc1 = _location(self.journey, 6.45, 3.40, heading=opposite)
        ri_svc._check_wrong_direction(self.journey, loc1)
        self.assertEqual(RouteDeviation.objects.filter(
            journey=self.journey, deviation_type='WRONG_DIRECTION', is_resolved=False).count(), 1)
        loc2 = _location(self.journey, 6.45, 3.40, heading=dest_b)
        ri_svc._check_wrong_direction(self.journey, loc2)
        self.assertEqual(RouteDeviation.objects.filter(
            journey=self.journey, deviation_type='WRONG_DIRECTION', is_resolved=False).count(), 0)


# ─── Story 5: Unexpected Stop Detection ───────────────────────────────────────

@override_settings(
    UNEXPECTED_STOP_SPEED_MS=0.5,
    UNEXPECTED_STOP_DURATION_S=10,  # short threshold for tests
)
class UnexpectedStopDetectionTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_r5')
        self.journey = _active_journey(self.passenger, reg='R5-001')

    def test_moving_vehicle_no_stop(self):
        loc = _location(self.journey, 6.45, 3.40, speed=10.0)
        result = ri_svc._check_unexpected_stop(self.journey, loc)
        self.assertIsNone(result)

    def test_slow_vehicle_creates_stop_record(self):
        loc = _location(self.journey, 6.45, 3.40, speed=0.1)
        result = ri_svc._check_unexpected_stop(self.journey, loc)
        self.assertIsNotNone(result)
        self.assertIsNone(result.ended_at)

    def test_stop_threshold_triggers_return(self):
        # Create a stop that started 20 s ago (> 10 s threshold).
        past = timezone.now() - timedelta(seconds=20)
        stop = UnexpectedStop.objects.create(
            journey=self.journey, latitude=6.45, longitude=3.40, started_at=past,
        )
        loc = _location(self.journey, 6.45, 3.40, speed=0.1)
        result = ri_svc._check_unexpected_stop(self.journey, loc)
        self.assertIsNotNone(result)
        self.assertEqual(result.id, stop.id)
        self.assertGreaterEqual(result.duration_s, 10)

    def test_resume_closes_open_stop(self):
        past = timezone.now() - timedelta(seconds=30)
        UnexpectedStop.objects.create(
            journey=self.journey, latitude=6.45, longitude=3.40, started_at=past,
        )
        loc = _location(self.journey, 6.45, 3.40, speed=5.0)
        ri_svc._check_unexpected_stop(self.journey, loc)
        stop = UnexpectedStop.objects.get(journey=self.journey)
        self.assertIsNotNone(stop.ended_at)
        self.assertTrue(stop.is_resolved)


# ─── Story 8: Risk Scoring ────────────────────────────────────────────────────

class RiskScoringTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_r8')
        self.journey = _active_journey(self.passenger, reg='R8-001')

    def test_no_events_gives_low_risk(self):
        risk = ri_svc._compute_risk(self.journey)
        self.assertEqual(risk.level, JourneyRisk.Level.LOW)
        self.assertAlmostEqual(risk.score, 0.0)

    def test_critical_deviation_raises_risk(self):
        RouteDeviation.objects.create(
            journey=self.journey, latitude=6.45, longitude=3.40,
            deviation_type=RouteDeviation.DeviationType.ROUTE_DEVIATION,
            severity=RouteDeviation.Severity.CRITICAL,
            distance_from_route_m=1500,
        )
        risk = ri_svc._compute_risk(self.journey)
        self.assertGreater(risk.score, 30)

    def test_multiple_factors_sum_correctly(self):
        RouteDeviation.objects.create(
            journey=self.journey, latitude=6.45, longitude=3.40,
            deviation_type=RouteDeviation.DeviationType.ROUTE_DEVIATION,
            severity=RouteDeviation.Severity.CRITICAL,
            distance_from_route_m=1500,
        )
        RouteDeviation.objects.create(
            journey=self.journey, latitude=6.45, longitude=3.40,
            deviation_type=RouteDeviation.DeviationType.WRONG_DIRECTION,
            severity=RouteDeviation.Severity.HIGH,
            heading_error_deg=150,
        )
        risk = ri_svc._compute_risk(self.journey)
        # route_deviation(50) + wrong_direction(25) = 75 → HIGH
        self.assertGreaterEqual(risk.score, 60)
        self.assertIn(risk.level, (JourneyRisk.Level.HIGH, JourneyRisk.Level.CRITICAL))

    def test_risk_capped_at_100(self):
        for _ in range(10):
            RouteDeviation.objects.create(
                journey=self.journey, latitude=6.45, longitude=3.40,
                deviation_type=RouteDeviation.DeviationType.ROUTE_DEVIATION,
                severity=RouteDeviation.Severity.CRITICAL,
                distance_from_route_m=2000,
            )
        risk = ri_svc._compute_risk(self.journey)
        self.assertLessEqual(risk.score, 100.0)

    def test_resolved_deviation_not_counted(self):
        RouteDeviation.objects.create(
            journey=self.journey, latitude=6.45, longitude=3.40,
            deviation_type=RouteDeviation.DeviationType.ROUTE_DEVIATION,
            severity=RouteDeviation.Severity.CRITICAL,
            distance_from_route_m=1500,
            is_resolved=True,
        )
        risk = ri_svc._compute_risk(self.journey)
        self.assertAlmostEqual(risk.score, 0.0)

    def test_risk_record_is_idempotent(self):
        ri_svc._compute_risk(self.journey)
        ri_svc._compute_risk(self.journey)
        self.assertEqual(JourneyRisk.objects.filter(journey=self.journey).count(), 1)


# ─── Story 9: Safety Warnings ─────────────────────────────────────────────────

class SafetyWarningTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_r9')
        self.journey = _active_journey(self.passenger, reg='R9-001')

    def test_route_deviation_event_creates_warning(self):
        ri_svc._emit_warning(self.journey, 'route.deviation.detected', {})
        self.assertEqual(JourneyWarning.objects.filter(
            journey=self.journey, warning_type='ROUTE_DEVIATION').count(), 1)

    def test_wrong_direction_event_creates_warning(self):
        ri_svc._emit_warning(self.journey, 'wrong.direction.detected', {})
        self.assertEqual(JourneyWarning.objects.filter(
            journey=self.journey, warning_type='WRONG_DIRECTION').count(), 1)

    def test_unexpected_stop_event_creates_warning(self):
        ri_svc._emit_warning(self.journey, 'unexpected.stop.detected', {})
        self.assertEqual(JourneyWarning.objects.filter(
            journey=self.journey, warning_type='UNEXPECTED_STOP').count(), 1)

    def test_journey_risk_updated_event_no_warning(self):
        before = JourneyWarning.objects.count()
        ri_svc._emit_warning(self.journey, 'journey.risk.updated', {})
        self.assertEqual(JourneyWarning.objects.count(), before)

    def test_high_risk_warning_created(self):
        risk = JourneyRisk.objects.create(
            journey=self.journey, score=65, level='HIGH',
        )
        w = ri_svc.create_high_risk_warning(self.journey, risk)
        self.assertIsNotNone(w)
        self.assertEqual(w.warning_type, 'HIGH_RISK')

    def test_high_risk_warning_not_duplicated(self):
        risk = JourneyRisk.objects.create(
            journey=self.journey, score=65, level='HIGH',
        )
        ri_svc.create_high_risk_warning(self.journey, risk)
        ri_svc.create_high_risk_warning(self.journey, risk)
        self.assertEqual(JourneyWarning.objects.filter(
            journey=self.journey, warning_type='HIGH_RISK', is_resolved=False).count(), 1)


# ─── Story 11: Incident Recommendation ────────────────────────────────────────

@override_settings(ROUTE_INTELLIGENCE_AUTO_ESCALATE=False)
class IncidentRecommendationTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_r11')
        self.journey = _active_journey(self.passenger, reg='R11-001')

    def test_critical_risk_creates_recommendation(self):
        risk = JourneyRisk.objects.create(
            journey=self.journey, score=85, level='CRITICAL',
        )
        ri_svc._recommend_or_escalate(self.journey, risk)
        self.assertEqual(JourneyWarning.objects.filter(
            journey=self.journey, warning_type='INCIDENT_RECOMMENDED').count(), 1)

    def test_recommendation_not_duplicated(self):
        risk = JourneyRisk.objects.create(
            journey=self.journey, score=85, level='CRITICAL',
        )
        ri_svc._recommend_or_escalate(self.journey, risk)
        ri_svc._recommend_or_escalate(self.journey, risk)
        self.assertEqual(JourneyWarning.objects.filter(
            journey=self.journey, warning_type='INCIDENT_RECOMMENDED',
            is_resolved=False).count(), 1)


# ─── Story 12: iSafePass Escalation ───────────────────────────────────────────

class ISafePassEscalationTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_r12')
        self.journey = _active_journey(self.passenger, reg='R12-001')
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_escalate_returns_none_when_bridge_not_configured(self):
        result = ri_svc.escalate_to_isafepass(self.journey, reason='Test')
        self.assertIsNone(result)

    def test_escalate_does_not_raise(self):
        try:
            ri_svc.escalate_to_isafepass(self.journey)
        except Exception as exc:
            self.fail(f'escalate_to_isafepass raised: {exc}')

    def test_escalate_api_endpoint_200(self):
        res = self.client.post(
            f'/api/v1/journeys/{self.journey.id}/escalate/',
            {'reason': 'Test escalation'},
            format='json',
        )
        self.assertEqual(res.status_code, 200)

    def test_escalate_api_marks_graceful_degradation(self):
        res = self.client.post(
            f'/api/v1/journeys/{self.journey.id}/escalate/', {}, format='json',
        )
        self.assertIn('not configured', res.data['detail'].lower())

    def test_escalate_wrong_journey_returns_403(self):
        other = _user('other_r12')
        c = APIClient()
        c.force_authenticate(other)
        res = c.post(
            f'/api/v1/journeys/{self.journey.id}/escalate/', {}, format='json',
        )
        self.assertEqual(res.status_code, 403)


# ─── Full analysis pipeline (Story 2) ─────────────────────────────────────────

@override_settings(
    ROUTE_DEVIATION_MINOR_M=200,
    ROUTE_DEVIATION_MAJOR_M=500,
    ROUTE_DEVIATION_CRITICAL_M=1000,
    WRONG_DIRECTION_THRESHOLD_DEG=90,
    UNEXPECTED_STOP_SPEED_MS=0.5,
    UNEXPECTED_STOP_DURATION_S=300,
    ROUTE_INTELLIGENCE_AUTO_ESCALATE=False,
)
class AnalysisPipelineTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_r2')
        self.journey = _active_journey(self.passenger, reg='R2-001')
        ri_svc.set_planned_route(self.journey, _waypoints_along_route())

    def test_on_route_location_no_deviations(self):
        loc = _location(self.journey, 6.52, 3.37, speed=15.0)
        ri_svc.analyze_location(self.journey, loc)
        self.assertEqual(RouteDeviation.objects.filter(
            journey=self.journey, is_resolved=False).count(), 0)

    def test_off_route_location_creates_deviation_and_warning(self):
        loc = _location(self.journey, 6.52, 3.50, speed=15.0)
        ri_svc.analyze_location(self.journey, loc)
        self.assertGreater(
            RouteDeviation.objects.filter(journey=self.journey, is_resolved=False).count(), 0
        )
        self.assertGreater(
            JourneyWarning.objects.filter(
                journey=self.journey, warning_type='ROUTE_DEVIATION').count(), 0
        )

    def test_risk_record_created_by_pipeline(self):
        loc = _location(self.journey, 6.52, 3.37, speed=15.0)
        ri_svc.analyze_location(self.journey, loc)
        self.assertTrue(JourneyRisk.objects.filter(journey=self.journey).exists())

    def test_pipeline_creates_risk_for_off_route(self):
        loc = _location(self.journey, 6.52, 3.80, speed=15.0)
        ri_svc.analyze_location(self.journey, loc)
        risk = JourneyRisk.objects.get(journey=self.journey)
        self.assertGreater(risk.score, 0)


# ─── API endpoints ─────────────────────────────────────────────────────────────

class RiskAPITest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_api')
        self.journey = _active_journey(self.passenger, reg='API-001')
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_risk_endpoint_returns_200(self):
        res = self.client.get(f'/api/v1/journeys/{self.journey.id}/risk/')
        self.assertEqual(res.status_code, 200)
        self.assertIn('score', res.data)
        self.assertIn('level', res.data)

    def test_risk_endpoint_initial_score_zero(self):
        res = self.client.get(f'/api/v1/journeys/{self.journey.id}/risk/')
        self.assertAlmostEqual(res.data['score'], 0.0)
        self.assertEqual(res.data['level'], 'LOW')

    def test_route_analysis_endpoint_returns_200(self):
        res = self.client.get(f'/api/v1/journeys/{self.journey.id}/route-analysis/')
        self.assertEqual(res.status_code, 200)
        self.assertIn('deviations', res.data)
        self.assertIn('warnings', res.data)
        self.assertIn('unexpected_stops', res.data)

    def test_warnings_endpoint_returns_200(self):
        res = self.client.get(f'/api/v1/journeys/{self.journey.id}/warnings/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, [])

    def test_warnings_endpoint_returns_warnings(self):
        JourneyWarning.objects.create(
            journey=self.journey, warning_type='ROUTE_DEVIATION',
            severity='WARNING', title='Test', message='Test warning',
        )
        res = self.client.get(f'/api/v1/journeys/{self.journey.id}/warnings/')
        self.assertEqual(len(res.data), 1)

    def test_active_only_filter(self):
        JourneyWarning.objects.create(
            journey=self.journey, warning_type='ROUTE_DEVIATION',
            severity='WARNING', title='Resolved', message='Old',
            is_resolved=True,
        )
        JourneyWarning.objects.create(
            journey=self.journey, warning_type='WRONG_DIRECTION',
            severity='DANGER', title='Active', message='Now',
        )
        res = self.client.get(
            f'/api/v1/journeys/{self.journey.id}/warnings/?active_only=1'
        )
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]['title'], 'Active')

    def test_other_user_gets_403(self):
        other = _user('other_api')
        c = APIClient()
        c.force_authenticate(other)
        for endpoint in ['risk', 'route-analysis', 'warnings']:
            res = c.get(f'/api/v1/journeys/{self.journey.id}/{endpoint}/')
            self.assertEqual(res.status_code, 403, f'{endpoint} should return 403')


class AdminRiskAPITest(TestCase):
    def setUp(self):
        self.admin = _user('admin_ri', is_staff=True)
        self.passenger = _user('pax_adm')
        self.journey = _active_journey(self.passenger, reg='ADM-001')
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_admin_high_risk_endpoint_accessible(self):
        res = self.client.get('/api/v1/admin/risk/high-risk/')
        self.assertEqual(res.status_code, 200)

    def test_admin_endpoint_lists_high_risk_journeys(self):
        JourneyRisk.objects.create(journey=self.journey, score=75, level='HIGH')
        res = self.client.get('/api/v1/admin/risk/high-risk/')
        self.assertEqual(len(res.data), 1)

    def test_admin_endpoint_excludes_low_risk(self):
        JourneyRisk.objects.create(journey=self.journey, score=10, level='LOW')
        res = self.client.get('/api/v1/admin/risk/high-risk/')
        self.assertEqual(len(res.data), 0)

    def test_non_admin_cannot_access(self):
        regular = _user('reg_adm')
        c = APIClient()
        c.force_authenticate(regular)
        res = c.get('/api/v1/admin/risk/high-risk/')
        self.assertEqual(res.status_code, 403)


# ─── Celery task (Story 2 — periodic monitor) ─────────────────────────────────

class MonitorTaskTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_task')
        self.journey = _active_journey(self.passenger, reg='TASK-001')

    def test_monitor_task_runs_without_error(self):
        from route_intelligence.tasks import monitor_active_journeys
        # No locations — task should skip gracefully.
        count = monitor_active_journeys()
        self.assertEqual(count, 0)

    def test_monitor_task_processes_journey_with_location(self):
        from route_intelligence.tasks import monitor_active_journeys
        _location(self.journey, 6.52, 3.37, speed=10.0)
        count = monitor_active_journeys()
        self.assertGreaterEqual(count, 1)

    def test_analyze_task_creates_risk_record(self):
        from route_intelligence.tasks import analyze_journey_location
        loc = _location(self.journey, 6.52, 3.37, speed=10.0)
        analyze_journey_location(str(self.journey.id), str(loc.id))
        self.assertTrue(JourneyRisk.objects.filter(journey=self.journey).exists())
