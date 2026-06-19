"""
Tests for Epic 3 — QR Identity & Verification System.

Stories covered:
  1  Participant QR generation (get-or-create)
  2  Asset QR generation (get-or-create)
  3  View QR detail
  4  Scan participant QR (valid)
  5  Scan asset QR (valid)
  6  Combined verify (participant + asset in one call)
  7  Invalid QR detection (bad sig, revoked, suspended, ineligible)
  8  QR revocation
  9  QR regeneration
  10 Scan history endpoints
  11 journey_eligible flag in verify response
  12 QRScan audit trail created on every verify attempt
"""
import io
import uuid
from datetime import date, timedelta

from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from accounts.models import User
from drivers.models import Driver, DriverVerification
from qr_codes.models import QRCode, QRScan
from qr_codes import services as qr_svc
from vehicles.models import Vehicle, VehicleVerification


# ─── helpers ──────────────────────────────────────────────────────────────────

def _user(username='alice', is_staff=False):
    return User.objects.create_user(
        username=username, email=f'{username}@example.com',
        password='pw', is_verified=True, is_staff=is_staff,
    )


def _verified_driver(user, days_valid=365):
    driver, _ = Driver.objects.get_or_create(
        user=user, defaults={'license_number': f'LIC-{user.pk}'},
    )
    expiry = date.today() + timedelta(days=days_valid)
    req, _ = DriverVerification.objects.get_or_create(
        driver=driver,
        defaults={'license_number': driver.license_number, 'license_expiry': expiry},
    )
    req.license_expiry = expiry
    req.status = DriverVerification.Status.APPROVED
    req.background_review_passed = True
    req.save()
    return driver


def _expired_driver(user):
    driver = _verified_driver(user, days_valid=-1)
    req = driver.verification
    req.license_expiry = date.today() - timedelta(days=1)
    req.save()
    return driver


def _verified_vehicle(user, reg='ABC-001', days_valid=365):
    vehicle, _ = Vehicle.objects.get_or_create(
        registration_number=reg,
        defaults={
            'owner': user, 'vehicle_type': 'SEDAN',
            'brand': 'Toyota', 'model': 'Corolla', 'year': 2020,
        },
    )
    expiry = date.today() + timedelta(days=days_valid)
    req, _ = VehicleVerification.objects.get_or_create(
        vehicle=vehicle,
        defaults={'owner': user, 'inspection_expiry': expiry, 'insurance_expiry': expiry},
    )
    req.inspection_expiry = expiry
    req.insurance_expiry = expiry
    req.status = VehicleVerification.Status.APPROVED
    req.save()
    return vehicle


# ─── Story 1: Participant QR generation ───────────────────────────────────────

class ParticipantQRGenerateTest(TestCase):
    def setUp(self):
        self.user = _user('driver1')
        self.driver = _verified_driver(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_generate_creates_qr(self):
        res = self.client.post('/api/v1/qr/participants/generate/')
        self.assertEqual(res.status_code, 200)
        self.assertIn('token', res.data)
        self.assertEqual(QRCode.objects.filter(
            entity_type=QRCode.EntityType.PARTICIPANT,
            status=QRCode.Status.ACTIVE,
        ).count(), 1)

    def test_generate_returns_existing_active_qr(self):
        self.client.post('/api/v1/qr/participants/generate/')
        self.client.post('/api/v1/qr/participants/generate/')
        self.assertEqual(QRCode.objects.filter(
            entity_type=QRCode.EntityType.PARTICIPANT,
        ).count(), 1)

    def test_unverified_driver_gets_403(self):
        self.driver.verification.status = DriverVerification.Status.PENDING
        self.driver.verification.save()
        res = self.client.post('/api/v1/qr/participants/generate/')
        self.assertEqual(res.status_code, 403)

    def test_expired_license_gets_403(self):
        req = self.driver.verification
        req.license_expiry = date.today() - timedelta(days=1)
        req.save()
        res = self.client.post('/api/v1/qr/participants/generate/')
        self.assertEqual(res.status_code, 403)

    def test_non_driver_gets_403(self):
        other = _user('passenger1')
        c = APIClient()
        c.force_authenticate(other)
        res = c.post('/api/v1/qr/participants/generate/')
        self.assertEqual(res.status_code, 403)

    def test_unauthenticated_gets_401(self):
        res = APIClient().post('/api/v1/qr/participants/generate/')
        self.assertEqual(res.status_code, 401)


# ─── Story 2: Asset QR generation ─────────────────────────────────────────────

class AssetQRGenerateTest(TestCase):
    def setUp(self):
        self.user = _user('owner1')
        self.vehicle = _verified_vehicle(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_generate_creates_qr(self):
        res = self.client.post('/api/v1/qr/assets/generate/', {'vehicle_id': self.vehicle.pk})
        self.assertEqual(res.status_code, 200)
        self.assertIn('token', res.data)

    def test_generate_returns_existing_active(self):
        self.client.post('/api/v1/qr/assets/generate/', {'vehicle_id': self.vehicle.pk})
        self.client.post('/api/v1/qr/assets/generate/', {'vehicle_id': self.vehicle.pk})
        self.assertEqual(QRCode.objects.filter(entity_type=QRCode.EntityType.ASSET).count(), 1)

    def test_unverified_vehicle_gets_403(self):
        self.vehicle.verification.status = VehicleVerification.Status.PENDING
        self.vehicle.verification.save()
        res = self.client.post('/api/v1/qr/assets/generate/', {'vehicle_id': self.vehicle.pk})
        self.assertEqual(res.status_code, 403)

    def test_wrong_owner_gets_403(self):
        other = _user('thief1')
        c = APIClient()
        c.force_authenticate(other)
        res = c.post('/api/v1/qr/assets/generate/', {'vehicle_id': self.vehicle.pk})
        self.assertEqual(res.status_code, 403)

    def test_missing_vehicle_id_gets_400(self):
        res = self.client.post('/api/v1/qr/assets/generate/', {})
        self.assertEqual(res.status_code, 400)


# ─── Story 3: View QR detail ──────────────────────────────────────────────────

class QRDetailViewTest(TestCase):
    def setUp(self):
        self.user = _user('driver2')
        self.driver = _verified_driver(self.user)
        self.qr = qr_svc.get_or_create_participant_qr(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_owner_can_view(self):
        res = self.client.get(f'/api/v1/qr/{self.qr.id}/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['id'], str(self.qr.id))

    def test_other_user_gets_403(self):
        other = _user('outsider1')
        c = APIClient()
        c.force_authenticate(other)
        res = c.get(f'/api/v1/qr/{self.qr.id}/')
        self.assertEqual(res.status_code, 403)

    def test_admin_can_view(self):
        admin = _user('admin1', is_staff=True)
        c = APIClient()
        c.force_authenticate(admin)
        res = c.get(f'/api/v1/qr/{self.qr.id}/')
        self.assertEqual(res.status_code, 200)

    def test_unknown_uuid_gets_404(self):
        res = self.client.get(f'/api/v1/qr/{uuid.uuid4()}/')
        self.assertEqual(res.status_code, 404)


# ─── Stories 4 & 11: Scan participant QR (valid + journey_eligible) ───────────

class VerifyParticipantQRTest(TestCase):
    def setUp(self):
        self.user = _user('driver3')
        self.driver = _verified_driver(self.user)
        self.qr = qr_svc.get_or_create_participant_qr(self.user)
        self.scanner = _user('scanner1')
        self.client = APIClient()
        self.client.force_authenticate(self.scanner)

    def test_valid_token_returns_valid(self):
        res = self.client.post('/api/v1/qr/verify/', {'token': self.qr.token})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data['valid'])
        self.assertEqual(res.data['result'], QRScan.Result.VALID)

    def test_journey_eligible_true_for_valid_driver(self):
        res = self.client.post('/api/v1/qr/verify/', {'token': self.qr.token})
        self.assertTrue(res.data['journey_eligible'])

    def test_scan_is_logged(self):
        before = QRScan.objects.count()
        self.client.post('/api/v1/qr/verify/', {'token': self.qr.token})
        self.assertEqual(QRScan.objects.count(), before + 1)
        scan = QRScan.objects.latest('scanned_at')
        self.assertEqual(scan.result, QRScan.Result.VALID)
        self.assertEqual(scan.qr_code, self.qr)

    def test_participant_block_in_response(self):
        res = self.client.post('/api/v1/qr/verify/', {'token': self.qr.token})
        self.assertIn('participant', res.data)


# ─── Story 5: Scan asset QR ───────────────────────────────────────────────────

class VerifyAssetQRTest(TestCase):
    def setUp(self):
        self.user = _user('owner2')
        self.vehicle = _verified_vehicle(self.user, reg='XYZ-002')
        self.qr = qr_svc.get_or_create_asset_qr(self.user, self.vehicle.pk)
        self.scanner = _user('scanner2')
        self.client = APIClient()
        self.client.force_authenticate(self.scanner)

    def test_valid_asset_token_returns_valid(self):
        res = self.client.post('/api/v1/qr/verify/', {'token': self.qr.token})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data['valid'])

    def test_asset_block_in_response(self):
        res = self.client.post('/api/v1/qr/verify/', {'token': self.qr.token})
        self.assertIn('asset', res.data)

    def test_journey_eligible_flag_present(self):
        res = self.client.post('/api/v1/qr/verify/', {'token': self.qr.token})
        self.assertIn('journey_eligible', res.data)


# ─── Story 6: Combined verify ─────────────────────────────────────────────────

class CombinedVerifyTest(TestCase):
    def setUp(self):
        self.user = _user('driver4')
        self.driver = _verified_driver(self.user)
        self.participant_qr = qr_svc.get_or_create_participant_qr(self.user)

        self.owner = _user('owner3')
        self.vehicle = _verified_vehicle(self.owner, reg='CMB-003')
        self.asset_qr = qr_svc.get_or_create_asset_qr(self.owner, self.vehicle.pk)

        self.scanner = _user('scanner3')
        self.client = APIClient()
        self.client.force_authenticate(self.scanner)

    def test_combined_verify_returns_both(self):
        res = self.client.post('/api/v1/qr/verify/', {
            'token': self.participant_qr.token,
            'asset_token': self.asset_qr.token,
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data['valid'])
        self.assertIn('asset', res.data)

    def test_two_scans_logged(self):
        before = QRScan.objects.count()
        self.client.post('/api/v1/qr/verify/', {
            'token': self.participant_qr.token,
            'asset_token': self.asset_qr.token,
        })
        self.assertEqual(QRScan.objects.count(), before + 2)


# ─── Story 7: Invalid QR detection ───────────────────────────────────────────

class InvalidQRTest(TestCase):
    def setUp(self):
        self.user = _user('driver5')
        self.driver = _verified_driver(self.user)
        self.qr = qr_svc.get_or_create_participant_qr(self.user)
        self.scanner = _user('scanner4')
        self.client = APIClient()
        self.client.force_authenticate(self.scanner)

    def test_bad_signature_returns_invalid(self):
        res = self.client.post('/api/v1/qr/verify/', {'token': 'garbage.token.here'})
        self.assertEqual(res.status_code, 400)
        self.assertFalse(res.data['valid'])
        self.assertEqual(res.data['result'], 'INVALID_TOKEN')

    def test_revoked_qr_returns_revoked(self):
        admin = _user('admin2', is_staff=True)
        qr_svc.revoke_qr(self.qr, admin=admin, reason='Test')
        res = self.client.post('/api/v1/qr/verify/', {'token': self.qr.token})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['result'], 'REVOKED')

    def test_suspended_driver_returns_suspended(self):
        self.driver.verification.status = DriverVerification.Status.SUSPENDED
        self.driver.verification.save()
        res = self.client.post('/api/v1/qr/verify/', {'token': self.qr.token})
        self.assertEqual(res.data['result'], 'SUSPENDED')

    def test_bad_sig_scan_is_logged(self):
        before = QRScan.objects.count()
        self.client.post('/api/v1/qr/verify/', {'token': 'bad'})
        self.assertEqual(QRScan.objects.count(), before + 1)
        self.assertEqual(QRScan.objects.latest('scanned_at').result, QRScan.Result.INVALID_TOKEN)


# ─── Story 8: Revocation ──────────────────────────────────────────────────────

class QRRevokeTest(TestCase):
    def setUp(self):
        self.user = _user('driver6')
        self.driver = _verified_driver(self.user)
        self.qr = qr_svc.get_or_create_participant_qr(self.user)
        self.admin = _user('admin3', is_staff=True)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_admin_can_revoke(self):
        res = self.client.post(f'/api/v1/qr/{self.qr.id}/revoke/', {'reason': 'stolen'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['status'], QRCode.Status.REVOKED)
        self.qr.refresh_from_db()
        self.assertEqual(self.qr.status, QRCode.Status.REVOKED)

    def test_revocation_idempotent(self):
        qr_svc.revoke_qr(self.qr)
        res = self.client.post(f'/api/v1/qr/{self.qr.id}/revoke/', {'reason': 'again'})
        self.assertEqual(res.status_code, 200)

    def test_non_admin_gets_403(self):
        c = APIClient()
        c.force_authenticate(self.user)
        res = c.post(f'/api/v1/qr/{self.qr.id}/revoke/', {'reason': 'test'})
        self.assertEqual(res.status_code, 403)


# ─── Story 9: Regeneration ────────────────────────────────────────────────────

class QRRegenerateTest(TestCase):
    def setUp(self):
        self.user = _user('driver7')
        self.driver = _verified_driver(self.user)
        self.qr = qr_svc.get_or_create_participant_qr(self.user)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_regenerate_revokes_old_and_creates_new(self):
        old_id = str(self.qr.id)
        res = self.client.post(f'/api/v1/qr/{self.qr.id}/regenerate/', {'reason': 'compromise'})
        self.assertEqual(res.status_code, 201)
        new_id = res.data['id']
        self.assertNotEqual(old_id, new_id)
        self.qr.refresh_from_db()
        self.assertEqual(self.qr.status, QRCode.Status.REVOKED)

    def test_new_qr_has_higher_generation(self):
        old_gen = self.qr.generation
        res = self.client.post(f'/api/v1/qr/{self.qr.id}/regenerate/', {'reason': 'test'})
        self.assertEqual(res.status_code, 201)
        new_qr = QRCode.objects.get(id=res.data['id'])
        self.assertGreater(new_qr.generation, old_gen)

    def test_other_user_cannot_regenerate(self):
        other = _user('outsider2')
        c = APIClient()
        c.force_authenticate(other)
        res = c.post(f'/api/v1/qr/{self.qr.id}/regenerate/', {'reason': 'test'})
        self.assertEqual(res.status_code, 403)


# ─── Story 10: Scan history ───────────────────────────────────────────────────

class QRScanHistoryTest(TestCase):
    def setUp(self):
        self.user = _user('driver8')
        self.driver = _verified_driver(self.user)
        self.qr = qr_svc.get_or_create_participant_qr(self.user)
        self.admin = _user('admin4', is_staff=True)
        self.scanner = _user('scanner5')

        # Create a scan
        qr_svc.verify_qr(self.qr.token, scanner=self.scanner)

        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_scan_list_returns_records(self):
        res = self.client.get('/api/v1/qr/scans/')
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(len(res.data), 1)

    def test_scan_list_filter_by_qr_id(self):
        res = self.client.get(f'/api/v1/qr/scans/?qr_id={self.qr.id}')
        self.assertEqual(res.status_code, 200)
        for item in res.data:
            self.assertEqual(str(item['qr_code']), str(self.qr.id))

    def test_scan_detail(self):
        scan = QRScan.objects.first()
        res = self.client.get(f'/api/v1/qr/scans/{scan.id}/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['id'], str(scan.id))

    def test_non_admin_cannot_see_scans(self):
        c = APIClient()
        c.force_authenticate(self.scanner)
        res = c.get('/api/v1/qr/scans/')
        self.assertEqual(res.status_code, 403)


# ─── Story 12: Audit trail metadata ──────────────────────────────────────────

class QRAuditTrailTest(TestCase):
    def setUp(self):
        self.user = _user('driver9')
        self.driver = _verified_driver(self.user)
        self.qr = qr_svc.get_or_create_participant_qr(self.user)
        self.scanner = _user('scanner6')

    def test_scan_stores_ip_and_user_agent(self):
        qr_svc.verify_qr(
            self.qr.token, scanner=self.scanner,
            ip='10.0.0.1', user_agent='TestAgent/1.0',
        )
        scan = QRScan.objects.latest('scanned_at')
        self.assertEqual(scan.ip_address, '10.0.0.1')
        self.assertEqual(scan.user_agent, 'TestAgent/1.0')
        self.assertEqual(scan.scanned_by, self.scanner)

    def test_scan_stores_location(self):
        qr_svc.verify_qr(
            self.qr.token, scanner=self.scanner,
            latitude=6.5244, longitude=3.3792,
        )
        scan = QRScan.objects.latest('scanned_at')
        self.assertAlmostEqual(scan.latitude, 6.5244, places=3)
        self.assertAlmostEqual(scan.longitude, 3.3792, places=3)

    def test_invalid_scan_still_logged(self):
        before = QRScan.objects.count()
        qr_svc.verify_qr('completelyinvalidtoken')
        self.assertEqual(QRScan.objects.count(), before + 1)
