"""
Tests for Epic 4 — Real-Time Journey Management.

Stories covered:
  1  Create journey (QR verification gate)
  2  Define destination
  3  Start journey
  5  Stream location updates (REST path)
  7  Journey event processing / timeline
  8  Pause journey
  9  Resume journey
  10 Complete journey
  11 Cancel journey
  12 Journey timeline endpoint
  13 Location dedup (reconnection handling)
  14 Journey history
  15 Active journey dashboard
"""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from drivers.models import Driver, DriverVerification
from journeys.models import Journey, JourneyEvent, JourneyLocation
from journeys import services as journey_svc
from qr_codes import services as qr_svc
from qr_codes.models import QRCode
from vehicles.models import Vehicle, VehicleVerification


# ─── fixtures ─────────────────────────────────────────────────────────────────

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


def _verified_vehicle(user, reg='TGX-001'):
    vehicle, _ = Vehicle.objects.get_or_create(
        registration_number=reg,
        defaults={
            'owner': user, 'vehicle_type': 'SEDAN',
            'brand': 'Toyota', 'model': 'Corolla', 'year': 2020,
        },
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


def _setup():
    """Return (passenger, driver_user, participant_token, asset_token)."""
    passenger = _user('passenger1')
    driver_user = _user('driverA')
    driver = _verified_driver(driver_user)
    vehicle = _verified_vehicle(driver_user, reg='JRN-001')

    p_qr = qr_svc.get_or_create_participant_qr(driver_user)
    a_qr = qr_svc.get_or_create_asset_qr(driver_user, vehicle.pk)
    return passenger, driver, vehicle, p_qr.token, a_qr.token


# ─── Story 1: Create journey ───────────────────────────────────────────────────

class JourneyCreateTest(TestCase):
    def setUp(self):
        self.passenger, self.driver, self.vehicle, self.ptok, self.atok = _setup()
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_create_journey_via_api(self):
        res = self.client.post('/api/v1/journeys/', {
            'participant_token': self.ptok,
            'asset_token': self.atok,
        })
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['status'], Journey.Status.CREATED)

    def test_journey_linked_to_passenger_driver_vehicle(self):
        res = self.client.post('/api/v1/journeys/', {
            'participant_token': self.ptok,
            'asset_token': self.atok,
        })
        self.assertEqual(res.data['passenger'], self.passenger.pk)
        self.assertEqual(res.data['driver'], self.driver.pk)
        self.assertEqual(res.data['vehicle'], self.vehicle.pk)

    def test_journey_created_event_logged(self):
        journey = journey_svc.create_journey(self.passenger, self.ptok, self.atok)
        self.assertTrue(
            JourneyEvent.objects.filter(
                journey=journey,
                event_type=JourneyEvent.EventType.CREATED,
            ).exists()
        )

    def test_invalid_participant_token_rejected(self):
        res = self.client.post('/api/v1/journeys/', {
            'participant_token': 'bad.token',
            'asset_token': self.atok,
        })
        self.assertEqual(res.status_code, 400)

    def test_invalid_asset_token_rejected(self):
        res = self.client.post('/api/v1/journeys/', {
            'participant_token': self.ptok,
            'asset_token': 'bad.token',
        })
        self.assertEqual(res.status_code, 400)

    def test_unauthenticated_rejected(self):
        res = APIClient().post('/api/v1/journeys/', {
            'participant_token': self.ptok, 'asset_token': self.atok,
        })
        self.assertEqual(res.status_code, 401)


# ─── Story 2: Define destination ──────────────────────────────────────────────

class JourneyDestinationTest(TestCase):
    def setUp(self):
        self.passenger, self.driver, self.vehicle, self.ptok, self.atok = _setup()
        self.journey = journey_svc.create_journey(self.passenger, self.ptok, self.atok)
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_set_destination(self):
        res = self.client.post(f'/api/v1/journeys/{self.journey.id}/destination/', {
            'origin_lat': 6.52, 'origin_lng': 3.37, 'origin_address': 'Lagos',
            'destination_lat': 6.60, 'destination_lng': 3.35, 'destination_address': 'Ikeja',
            'estimated_distance_m': 15000, 'estimated_duration_s': 1800,
        })
        self.assertEqual(res.status_code, 200)
        self.journey.refresh_from_db()
        self.assertAlmostEqual(self.journey.destination_lat, 6.60)
        self.assertEqual(self.journey.estimated_duration_s, 1800)

    def test_destination_event_logged(self):
        self.client.post(f'/api/v1/journeys/{self.journey.id}/destination/', {
            'origin_lat': 6.52, 'origin_lng': 3.37,
            'destination_lat': 6.60, 'destination_lng': 3.35,
        })
        self.assertTrue(
            JourneyEvent.objects.filter(
                journey=self.journey,
                event_type=JourneyEvent.EventType.DESTINATION_SET,
            ).exists()
        )

    def test_other_user_cannot_set_destination(self):
        other = _user('outsider')
        c = APIClient()
        c.force_authenticate(other)
        res = c.post(f'/api/v1/journeys/{self.journey.id}/destination/', {
            'origin_lat': 6.52, 'origin_lng': 3.37,
            'destination_lat': 6.60, 'destination_lng': 3.35,
        })
        self.assertEqual(res.status_code, 403)


# ─── Story 3: Start journey ────────────────────────────────────────────────────

class JourneyStartTest(TestCase):
    def setUp(self):
        self.passenger, self.driver, self.vehicle, self.ptok, self.atok = _setup()
        self.journey = journey_svc.create_journey(self.passenger, self.ptok, self.atok)
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_start_changes_status_to_active(self):
        res = self.client.post(f'/api/v1/journeys/{self.journey.id}/start/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], Journey.Status.ACTIVE)

    def test_start_records_timestamp(self):
        self.client.post(f'/api/v1/journeys/{self.journey.id}/start/')
        self.journey.refresh_from_db()
        self.assertIsNotNone(self.journey.started_at)

    def test_started_event_logged(self):
        journey_svc.start_journey(self.journey, self.passenger)
        self.assertTrue(
            JourneyEvent.objects.filter(
                journey=self.journey, event_type=JourneyEvent.EventType.STARTED,
            ).exists()
        )

    def test_cannot_start_already_active(self):
        journey_svc.start_journey(self.journey, self.passenger)
        with self.assertRaises(journey_svc.JourneyError):
            journey_svc.start_journey(self.journey, self.passenger)

    def test_other_user_cannot_start(self):
        other = _user('interloper')
        c = APIClient()
        c.force_authenticate(other)
        res = c.post(f'/api/v1/journeys/{self.journey.id}/start/')
        self.assertEqual(res.status_code, 403)


# ─── Story 5: Location updates ────────────────────────────────────────────────

class JourneyLocationTest(TestCase):
    def setUp(self):
        self.passenger, self.driver, self.vehicle, self.ptok, self.atok = _setup()
        self.journey = journey_svc.create_journey(self.passenger, self.ptok, self.atok)
        journey_svc.start_journey(self.journey, self.passenger)
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_post_location_creates_record(self):
        res = self.client.post(f'/api/v1/journeys/{self.journey.id}/locations/', {
            'latitude': 6.52, 'longitude': 3.37, 'speed': 15.0, 'heading': 90.0,
        })
        self.assertEqual(res.status_code, 201)
        self.assertEqual(JourneyLocation.objects.filter(journey=self.journey).count(), 1)

    def test_location_on_inactive_journey_rejected(self):
        journey_svc.pause_journey(self.journey, self.passenger)
        res = self.client.post(f'/api/v1/journeys/{self.journey.id}/locations/', {
            'latitude': 6.52, 'longitude': 3.37,
        })
        self.assertEqual(res.status_code, 400)


# ─── Story 7 & 12: Events + timeline ─────────────────────────────────────────

class JourneyTimelineTest(TestCase):
    def setUp(self):
        self.passenger, self.driver, self.vehicle, self.ptok, self.atok = _setup()
        self.journey = journey_svc.create_journey(self.passenger, self.ptok, self.atok)
        journey_svc.start_journey(self.journey, self.passenger)
        journey_svc.pause_journey(self.journey, self.passenger, 'traffic')
        journey_svc.resume_journey(self.journey, self.passenger)
        journey_svc.complete_journey(self.journey, self.passenger)
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_timeline_endpoint_returns_ordered_events(self):
        res = self.client.get(f'/api/v1/journeys/{self.journey.id}/timeline/')
        self.assertEqual(res.status_code, 200)
        types = [e['event_type'] for e in res.data]
        self.assertIn(JourneyEvent.EventType.CREATED, types)
        self.assertIn(JourneyEvent.EventType.STARTED, types)
        self.assertIn(JourneyEvent.EventType.PAUSED, types)
        self.assertIn(JourneyEvent.EventType.RESUMED, types)
        self.assertIn(JourneyEvent.EventType.COMPLETED, types)

    def test_timeline_chronological(self):
        res = self.client.get(f'/api/v1/journeys/{self.journey.id}/timeline/')
        timestamps = [e['timestamp'] for e in res.data]
        self.assertEqual(timestamps, sorted(timestamps))


# ─── Story 8: Pause ───────────────────────────────────────────────────────────

class JourneyPauseTest(TestCase):
    def setUp(self):
        self.passenger, self.driver, self.vehicle, self.ptok, self.atok = _setup()
        self.journey = journey_svc.create_journey(self.passenger, self.ptok, self.atok)
        journey_svc.start_journey(self.journey, self.passenger)
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_pause_changes_status(self):
        res = self.client.post(f'/api/v1/journeys/{self.journey.id}/pause/', {'reason': 'fuel'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], Journey.Status.PAUSED)

    def test_pause_records_reason(self):
        journey_svc.pause_journey(self.journey, self.passenger, reason='traffic')
        self.journey.refresh_from_db()
        self.assertEqual(self.journey.pause_reason, 'traffic')

    def test_cannot_pause_completed_journey(self):
        journey_svc.complete_journey(self.journey, self.passenger)
        with self.assertRaises(journey_svc.JourneyError):
            journey_svc.pause_journey(self.journey, self.passenger)


# ─── Story 9: Resume ──────────────────────────────────────────────────────────

class JourneyResumeTest(TestCase):
    def setUp(self):
        self.passenger, self.driver, self.vehicle, self.ptok, self.atok = _setup()
        self.journey = journey_svc.create_journey(self.passenger, self.ptok, self.atok)
        journey_svc.start_journey(self.journey, self.passenger)
        journey_svc.pause_journey(self.journey, self.passenger)
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_resume_changes_status_to_active(self):
        res = self.client.post(f'/api/v1/journeys/{self.journey.id}/resume/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], Journey.Status.ACTIVE)

    def test_cannot_resume_active_journey(self):
        journey_svc.resume_journey(self.journey, self.passenger)
        with self.assertRaises(journey_svc.JourneyError):
            journey_svc.resume_journey(self.journey, self.passenger)

    def test_resume_event_logged(self):
        journey_svc.resume_journey(self.journey, self.passenger)
        self.assertTrue(
            JourneyEvent.objects.filter(
                journey=self.journey, event_type=JourneyEvent.EventType.RESUMED,
            ).exists()
        )


# ─── Story 10: Complete ────────────────────────────────────────────────────────

class JourneyCompleteTest(TestCase):
    def setUp(self):
        self.passenger, self.driver, self.vehicle, self.ptok, self.atok = _setup()
        self.journey = journey_svc.create_journey(self.passenger, self.ptok, self.atok)
        journey_svc.start_journey(self.journey, self.passenger)
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_complete_changes_status(self):
        res = self.client.post(f'/api/v1/journeys/{self.journey.id}/complete/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], Journey.Status.COMPLETED)

    def test_complete_records_timestamp(self):
        journey_svc.complete_journey(self.journey, self.passenger)
        self.journey.refresh_from_db()
        self.assertIsNotNone(self.journey.completed_at)

    def test_cannot_complete_already_completed(self):
        journey_svc.complete_journey(self.journey, self.passenger)
        with self.assertRaises(journey_svc.JourneyError):
            journey_svc.complete_journey(self.journey, self.passenger)

    def test_duration_seconds_calculated(self):
        journey_svc.complete_journey(self.journey, self.passenger)
        self.journey.refresh_from_db()
        self.assertIsNotNone(self.journey.duration_seconds)
        self.assertGreaterEqual(self.journey.duration_seconds, 0)


# ─── Story 11: Cancel ─────────────────────────────────────────────────────────

class JourneyCancelTest(TestCase):
    def setUp(self):
        self.passenger, self.driver, self.vehicle, self.ptok, self.atok = _setup()
        self.journey = journey_svc.create_journey(self.passenger, self.ptok, self.atok)
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_cancel_changes_status(self):
        res = self.client.post(f'/api/v1/journeys/{self.journey.id}/cancel/',
                               {'reason': 'wrong vehicle'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], Journey.Status.CANCELLED)

    def test_cancel_records_reason(self):
        journey_svc.cancel_journey(self.journey, self.passenger, reason='mistake')
        self.journey.refresh_from_db()
        self.assertEqual(self.journey.cancellation_reason, 'mistake')

    def test_cannot_cancel_completed_journey(self):
        journey_svc.start_journey(self.journey, self.passenger)
        journey_svc.complete_journey(self.journey, self.passenger)
        with self.assertRaises(journey_svc.JourneyError):
            journey_svc.cancel_journey(self.journey, self.passenger)


# ─── Story 13: Location dedup ─────────────────────────────────────────────────

class LocationDedupTest(TestCase):
    def setUp(self):
        self.passenger, self.driver, self.vehicle, self.ptok, self.atok = _setup()
        self.journey = journey_svc.create_journey(self.passenger, self.ptok, self.atok)
        journey_svc.start_journey(self.journey, self.passenger)

    def test_duplicate_client_timestamp_not_duplicated(self):
        from django.utils import timezone
        ts = timezone.now()
        journey_svc.record_location(self.journey, 6.52, 3.37, client_timestamp=ts)
        journey_svc.record_location(self.journey, 6.53, 3.38, client_timestamp=ts)
        self.assertEqual(
            JourneyLocation.objects.filter(journey=self.journey, client_timestamp=ts).count(), 1
        )

    def test_different_timestamps_both_recorded(self):
        from django.utils import timezone
        from datetime import timedelta as td
        t1 = timezone.now()
        t2 = t1 + td(seconds=5)
        journey_svc.record_location(self.journey, 6.52, 3.37, client_timestamp=t1)
        journey_svc.record_location(self.journey, 6.53, 3.38, client_timestamp=t2)
        self.assertEqual(JourneyLocation.objects.filter(journey=self.journey).count(), 2)


# ─── Story 14: Journey history ────────────────────────────────────────────────

class JourneyHistoryTest(TestCase):
    def setUp(self):
        self.passenger, self.driver, self.vehicle, self.ptok, self.atok = _setup()
        j = journey_svc.create_journey(self.passenger, self.ptok, self.atok)
        journey_svc.start_journey(j, self.passenger)
        journey_svc.complete_journey(j, self.passenger)
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_history_returns_completed_journeys(self):
        res = self.client.get('/api/v1/journeys/history/')
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(len(res.data), 1)
        for j in res.data:
            self.assertIn(j['status'], [Journey.Status.COMPLETED, Journey.Status.CANCELLED])


# ─── Story 15: Active dashboard ───────────────────────────────────────────────

class ActiveJourneyDashboardTest(TestCase):
    def setUp(self):
        self.passenger, self.driver, self.vehicle, self.ptok, self.atok = _setup()
        self.journey = journey_svc.create_journey(self.passenger, self.ptok, self.atok)
        journey_svc.start_journey(self.journey, self.passenger)
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_active_endpoint_returns_active_journey(self):
        res = self.client.get('/api/v1/journeys/active/')
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(len(res.data), 1)
        for j in res.data:
            self.assertIn(j['status'], [Journey.Status.ACTIVE, Journey.Status.PAUSED])

    def test_completed_not_in_active(self):
        journey_svc.complete_journey(self.journey, self.passenger)
        res = self.client.get('/api/v1/journeys/active/')
        ids = [j['id'] for j in res.data]
        self.assertNotIn(str(self.journey.id), ids)


# ─── Journey list + detail ────────────────────────────────────────────────────

class JourneyListDetailTest(TestCase):
    def setUp(self):
        self.passenger, self.driver, self.vehicle, self.ptok, self.atok = _setup()
        self.journey = journey_svc.create_journey(self.passenger, self.ptok, self.atok)
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_list_returns_my_journeys(self):
        res = self.client.get('/api/v1/journeys/')
        self.assertEqual(res.status_code, 200)
        ids = [j['id'] for j in res.data]
        self.assertIn(str(self.journey.id), ids)

    def test_detail_returns_journey(self):
        res = self.client.get(f'/api/v1/journeys/{self.journey.id}/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['id'], str(self.journey.id))

    def test_other_user_cannot_see_journey(self):
        other = _user('snoop')
        c = APIClient()
        c.force_authenticate(other)
        res = c.get(f'/api/v1/journeys/{self.journey.id}/')
        self.assertEqual(res.status_code, 403)

    def test_driver_can_see_journey(self):
        c = APIClient()
        c.force_authenticate(self.driver.user)
        res = c.get(f'/api/v1/journeys/{self.journey.id}/')
        self.assertEqual(res.status_code, 200)
