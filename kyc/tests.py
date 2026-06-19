"""KYC & Verification Management — test suite (Phase F).

Covers all twelve acceptance-criteria stories:
  1–3  Identity submission & admin approve/reject
  4–5  Driver verification (gating, license expiry)
  6–7  Vehicle QR eligibility (verified + valid inspection)
  8    QR code eligibility (driver side)
  9    (Operator flow — similar pattern; core logic tested via service)
  10   KYC status dashboard
  11   Reverification: expired docs suspend entity; soon-to-expire triggers reminder
  12   Trust score calculation (factor weighting)
"""
import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from rest_framework import status
from rest_framework.test import APITestCase

from common import storage as common_storage
from common.models import VerificationDocument
from common.services import verification as ver_svc
from common.services.badges import badges_for, badges_for_vehicle
from common.services.trust import compute as trust_compute
from drivers import services as driver_svc
from drivers.models import Driver, DriverVerification
from kyc.models import IdentityVerification, ReviewEvent, VerificationStatus
from kyc.services import kyc_service, qr_service
from kyc.tasks import scan_expiring_documents
from notifications.models import Notification
from vehicles.models import Vehicle, VehicleVerification

User = get_user_model()


# ─── helpers ──────────────────────────────────────────────────────────────────

def _fake(name='doc.jpg', data=b'\xff\xd8\xff\xe0'):
    """Minimal in-memory file for FileField upload slots (no image validation)."""
    return SimpleUploadedFile(name, data, content_type='image/jpeg')


def _img(name='face.png'):
    """1×1 white PNG via Pillow — passes ImageField validation (used for selfies)."""
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (1, 1), color='white').save(buf, format='PNG')
    return SimpleUploadedFile(name, buf.getvalue(), content_type='image/png')


class _Base(APITestCase):
    """Routes private_storage writes to a throwaway temp directory.

    ``private_storage`` is a module-level singleton whose ``location`` is set at
    import time.  Patching it here (and restoring in tearDownClass) means every
    ``VerificationDocument`` saved during the class writes to a temp dir instead
    of the real ``PRIVATE_MEDIA_ROOT``, and the authenticated download endpoint
    can serve them back without touching the filesystem outside the test sandbox.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmpdir = tempfile.mkdtemp()
        _p = Path(cls._tmpdir)
        cls._orig_loc = common_storage.private_storage.location
        cls._orig_base = getattr(common_storage.private_storage, 'base_location', None)
        common_storage.private_storage.location = _p
        common_storage.private_storage.base_location = str(_p)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        common_storage.private_storage.location = cls._orig_loc
        if cls._orig_base is not None:
            common_storage.private_storage.base_location = cls._orig_base
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    # ── user factory ─────────────────────────────────────────────────────────

    def _user(self, name, *, staff=False, **kw):
        return User.objects.create_user(
            username=name,
            email=f'{name}@test.example',
            password='pw',
            is_verified=True,
            is_staff=staff,
            **kw,
        )

    # ── workflow shortcuts ────────────────────────────────────────────────────

    def _approve_identity(self, user):
        req = kyc_service.submit_identity(
            user,
            primary_id_type=IdentityVerification.IDType.NATIONAL_ID,
            id_document=_fake('id.jpg'),
        )
        kyc_service.approve(req)
        user.refresh_from_db()
        return req

    def _approve_driver(self, user, license_expiry=None):
        expiry = license_expiry or (date.today() + timedelta(days=365))
        req = driver_svc.submit_driver_verification(
            user,
            license_number='DL-001',
            license_expiry=expiry,
            national_id=_fake('n.jpg'),
            driver_license=_fake('dl.jpg'),
        )
        driver_svc.approve(req)
        user.refresh_from_db()
        return req


# ─── Stories 1–3: identity submission & admin review ──────────────────────────

class IdentitySubmitAPITest(_Base):
    """Story 1 — user submits identity documents via the API."""

    def setUp(self):
        self.user = self._user('alice')
        self.client.force_authenticate(self.user)

    def test_submit_returns_201_pending(self):
        resp = self.client.post(
            reverse('kyc:identity'),
            {'primary_id_type': 'NATIONAL_ID', 'id_document': _fake()},
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['status'], VerificationStatus.PENDING)

    def test_submit_stores_document_privately(self):
        self.client.post(
            reverse('kyc:identity'),
            {'primary_id_type': 'NATIONAL_ID', 'id_document': _fake()},
            format='multipart',
        )
        self.assertTrue(VerificationDocument.objects.filter(owner=self.user).exists())

    def test_level_unchanged_before_admin_approval(self):
        self.client.post(
            reverse('kyc:identity'),
            {'primary_id_type': 'NATIONAL_ID', 'id_document': _fake()},
            format='multipart',
        )
        self.user.refresh_from_db()
        self.assertLess(self.user.verification_level, User.VerificationLevel.IDENTITY)

    def test_unauthenticated_rejected(self):
        self.client.force_authenticate(None)
        resp = self.client.post(
            reverse('kyc:identity'),
            {'primary_id_type': 'NATIONAL_ID', 'id_document': _fake()},
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_selfie_endpoint_accepts_upload(self):
        """Story 2 — selfie attached separately (must be a valid image)."""
        resp = self.client.post(
            reverse('kyc:selfie'),
            {'selfie': _img('selfie.png')},
            format='multipart',
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)


class IdentityApproveTest(_Base):
    """Story 3 — admin approve/reject flow."""

    def setUp(self):
        self.admin = self._user('admin_user', staff=True)
        self.user = self._user('bob')

    def test_approve_sets_status_approved(self):
        req = kyc_service.submit_identity(self.user, 'NATIONAL_ID', _fake())
        kyc_service.approve(req, admin=self.admin)
        req.refresh_from_db()
        self.assertEqual(req.status, VerificationStatus.APPROVED)

    def test_approve_bumps_verification_level_to_identity(self):
        req = kyc_service.submit_identity(self.user, 'NATIONAL_ID', _fake())
        kyc_service.approve(req, admin=self.admin)
        self.user.refresh_from_db()
        self.assertEqual(self.user.verification_level, User.VerificationLevel.IDENTITY)

    def test_approve_adds_identity_badge(self):
        self._approve_identity(self.user)
        self.assertIn('Identity Verified', badges_for(self.user))

    def test_approve_raises_trust_score(self):
        self._approve_identity(self.user)
        self.assertGreater(self.user.trust_score, 0)

    def test_approve_creates_kyc_notification(self):
        req = kyc_service.submit_identity(self.user, 'NATIONAL_ID', _fake())
        kyc_service.approve(req, admin=self.admin)
        self.assertTrue(
            Notification.objects.filter(
                user=self.user, type=Notification.Type.KYC_UPDATE,
            ).exists()
        )

    def test_approve_writes_review_event(self):
        req = kyc_service.submit_identity(self.user, 'NATIONAL_ID', _fake())
        kyc_service.approve(req, admin=self.admin)
        self.assertTrue(ReviewEvent.objects.filter(action=ReviewEvent.Action.APPROVED).exists())

    def test_reject_leaves_level_below_identity(self):
        req = kyc_service.submit_identity(self.user, 'NATIONAL_ID', _fake())
        kyc_service.reject(req, admin=self.admin, reason='Unreadable document.')
        self.user.refresh_from_db()
        self.assertLess(self.user.verification_level, User.VerificationLevel.IDENTITY)

    def test_reject_sets_status_rejected(self):
        req = kyc_service.submit_identity(self.user, 'NATIONAL_ID', _fake())
        kyc_service.reject(req, admin=self.admin, reason='Bad photo.')
        req.refresh_from_db()
        self.assertEqual(req.status, VerificationStatus.REJECTED)

    def test_request_more_info_sets_status(self):
        req = kyc_service.submit_identity(self.user, 'NATIONAL_ID', _fake())
        kyc_service.request_more_info(req, admin=self.admin, reason='Need clearer selfie.')
        req.refresh_from_db()
        self.assertEqual(req.status, VerificationStatus.MORE_INFO)


# ─── Story 10: KYC status dashboard ──────────────────────────────────────────

class KYCStatusDashboardTest(_Base):

    def setUp(self):
        self.user = self._user('status_user')
        self.client.force_authenticate(self.user)

    def test_unverified_user_dashboard(self):
        resp = self.client.get(reverse('kyc:status'))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data['checks']['identity_verified'])
        self.assertEqual(resp.data['identity_status'], VerificationStatus.NOT_SUBMITTED)

    def test_dashboard_shows_identity_verified_after_approval(self):
        self._approve_identity(self.user)
        resp = self.client.get(reverse('kyc:status'))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.data['checks']['identity_verified'])
        self.assertIn('Identity Verified', resp.data['badges'])
        self.assertGreater(resp.data['trust_score'], 0)

    def test_dashboard_shows_driver_verified_after_approval(self):
        self._approve_identity(self.user)
        self._approve_driver(self.user)
        resp = self.client.get(reverse('kyc:status'))
        self.assertTrue(resp.data['checks']['driver_verified'])
        self.assertIn('Verified Driver', resp.data['badges'])


# ─── Private document download endpoint ───────────────────────────────────────

class DocumentDownloadTest(_Base):
    """Authenticated download endpoint: owner+staff allowed, others blocked."""

    def setUp(self):
        self.owner = self._user('carol')
        self.stranger = self._user('dave')
        self.staff = self._user('staff_mem', staff=True)
        # submit_identity saves a real file to the temp dir so the view can serve it
        req = kyc_service.submit_identity(self.owner, 'NATIONAL_ID', _fake('id.jpg'))
        ct = ContentType.objects.get_for_model(req)
        self.doc = VerificationDocument.objects.filter(
            content_type=ct, object_id=str(req.pk), owner=self.owner,
        ).first()
        self.url = reverse('document-download', kwargs={'pk': self.doc.pk})

    def test_unauthenticated_gets_401(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_owner_gets_404(self):
        self.client.force_authenticate(self.stranger)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_owner_can_download(self):
        self.client.force_authenticate(self.owner)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_staff_can_download(self):
        self.client.force_authenticate(self.staff)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


# ─── Stories 4–5: driver verification (gating + license expiry) ───────────────

class DriverVerificationTest(_Base):

    def setUp(self):
        self.user = self._user('driver_user')

    # -- gating

    def test_service_raises_if_identity_not_approved(self):
        with self.assertRaises(driver_svc.VerificationError):
            driver_svc.submit_driver_verification(
                self.user, 'DL-001',
                date.today() + timedelta(days=365),
                _fake('n.jpg'), _fake('dl.jpg'),
            )

    def test_api_returns_403_if_identity_not_approved(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post(reverse('drivers:verification'), {
            'license_number': 'DL-001',
            'license_expiry': (date.today() + timedelta(days=365)).isoformat(),
            'national_id': _fake('n.jpg'),
            'driver_license': _fake('dl.jpg'),
        }, format='multipart')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    # -- approval flow

    def test_approve_sets_status_approved(self):
        self._approve_identity(self.user)
        req = self._approve_driver(self.user)
        req.refresh_from_db()
        self.assertEqual(req.status, DriverVerification.Status.APPROVED)

    def test_approve_bumps_user_level_to_driver(self):
        self._approve_identity(self.user)
        self._approve_driver(self.user)
        self.assertEqual(self.user.verification_level, User.VerificationLevel.DRIVER)

    def test_approve_sets_driver_status_verified(self):
        self._approve_identity(self.user)
        self._approve_driver(self.user)
        self.assertEqual(
            Driver.objects.get(user=self.user).verification_status,
            Driver.VerificationStatus.VERIFIED,
        )

    def test_can_operate_true_after_approval_with_valid_license(self):
        self._approve_identity(self.user)
        req = self._approve_driver(self.user)
        req.refresh_from_db()
        self.assertTrue(req.can_operate)

    def test_can_operate_false_when_license_expired(self):
        self._approve_identity(self.user)
        req = self._approve_driver(self.user, license_expiry=date.today() - timedelta(days=1))
        req.refresh_from_db()
        self.assertFalse(req.can_operate)

    def test_driver_badge_appears_after_approval(self):
        self._approve_identity(self.user)
        self._approve_driver(self.user)
        self.assertIn('Verified Driver', badges_for(self.user))

    def test_trust_score_rises_after_driver_approval(self):
        self._approve_identity(self.user)
        score_after_identity = self.user.trust_score
        self._approve_driver(self.user)
        self.assertGreater(self.user.trust_score, score_after_identity)


# ─── Story 8: driver QR code eligibility ──────────────────────────────────────

class DriverQRTest(_Base):

    def setUp(self):
        self.user = self._user('qr_driver')

    def test_qr_denied_for_unverified_driver(self):
        self.client.force_authenticate(self.user)
        resp = self.client.get(reverse('drivers:qr'))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_qr_denied_when_license_expired(self):
        self._approve_identity(self.user)
        self._approve_driver(self.user, license_expiry=date.today() - timedelta(days=1))
        self.client.force_authenticate(self.user)
        resp = self.client.get(reverse('drivers:qr'))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_qr_png_returned_for_verified_driver(self):
        self._approve_identity(self.user)
        self._approve_driver(self.user)
        self.client.force_authenticate(self.user)
        resp = self.client.get(reverse('drivers:qr'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.get('Content-Type'), 'image/png')

    def test_qr_json_format_returns_token_and_url(self):
        self._approve_identity(self.user)
        self._approve_driver(self.user)
        self.client.force_authenticate(self.user)
        resp = self.client.get(reverse('drivers:qr'), {'format': 'json'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('token', resp.data)
        self.assertIn('verify_url', resp.data)


# ─── Stories 6–7: vehicle verification + QR ───────────────────────────────────

class VehicleQRTest(_Base):

    def setUp(self):
        self.user = self._user('vehicle_owner')

    def _make_verified_vehicle(self, inspection_expiry=None):
        expiry = inspection_expiry or (date.today() + timedelta(days=180))
        vehicle = Vehicle.objects.create(
            owner=self.user, registration_number='VHC-001',
            vehicle_type='CAR', brand='Toyota', model='Camry',
            year=2022, is_verified=True,
        )
        VehicleVerification.objects.create(
            vehicle=vehicle, owner=self.user,
            status=VehicleVerification.Status.APPROVED,
            inspection_expiry=expiry,
        )
        return vehicle

    def test_qr_denied_for_unverified_vehicle(self):
        vehicle = Vehicle.objects.create(
            owner=self.user, registration_number='UNV-001',
            vehicle_type='CAR', brand='Honda', model='Civic', year=2020,
        )
        self.client.force_authenticate(self.user)
        resp = self.client.get(reverse('vehicles:qr', kwargs={'pk': vehicle.pk}))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_qr_denied_when_inspection_expired(self):
        vehicle = self._make_verified_vehicle(
            inspection_expiry=date.today() - timedelta(days=1),
        )
        self.client.force_authenticate(self.user)
        resp = self.client.get(reverse('vehicles:qr', kwargs={'pk': vehicle.pk}))
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_qr_png_returned_for_eligible_vehicle(self):
        vehicle = self._make_verified_vehicle()
        self.client.force_authenticate(self.user)
        resp = self.client.get(reverse('vehicles:qr', kwargs={'pk': vehicle.pk}))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.get('Content-Type'), 'image/png')

    def test_verified_vehicle_badge(self):
        vehicle = self._make_verified_vehicle()
        self.assertIn('Verified Vehicle', badges_for_vehicle(vehicle))


# ─── Public scan-verify endpoint ──────────────────────────────────────────────

class PublicVerifyTest(_Base):

    def setUp(self):
        self.user = self._user('scan_target')

    def test_valid_driver_token_returns_summary(self):
        self._approve_identity(self.user)
        self._approve_driver(self.user)
        driver = Driver.objects.get(user=self.user)
        token = qr_service.make_token('driver', driver.pk)
        resp = self.client.get(reverse('public-verify', kwargs={'token': token}))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['entity'], 'driver')
        self.assertTrue(resp.data['verified'])
        self.assertIn('Verified Driver', resp.data['badges'])

    def test_expired_license_makes_driver_not_verified(self):
        self._approve_identity(self.user)
        self._approve_driver(self.user, license_expiry=date.today() - timedelta(days=1))
        driver = Driver.objects.get(user=self.user)
        token = qr_service.make_token('driver', driver.pk)
        resp = self.client.get(reverse('public-verify', kwargs={'token': token}))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertFalse(resp.data['verified'])

    def test_tampered_token_returns_400(self):
        resp = self.client.get(reverse('public-verify', kwargs={'token': 'bad.token'}))
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_valid_vehicle_token_returns_summary(self):
        vehicle = Vehicle.objects.create(
            owner=self.user, registration_number='VHC-PUB',
            vehicle_type='CAR', brand='Kia', model='Rio', year=2021, is_verified=True,
        )
        VehicleVerification.objects.create(
            vehicle=vehicle, owner=self.user,
            status=VehicleVerification.Status.APPROVED,
            inspection_expiry=date.today() + timedelta(days=90),
        )
        token = qr_service.make_token('vehicle', vehicle.pk)
        resp = self.client.get(reverse('public-verify', kwargs={'token': token}))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['entity'], 'vehicle')
        self.assertTrue(resp.data['verified'])


# ─── Story 11: reverification — expiry scan task ──────────────────────────────

class ExpiredDocumentScanTest(_Base):
    """scan_expiring_documents() suspends verified entities on expired critical docs
    and sends reminders for docs expiring within VERIFICATION_REMINDER_DAYS."""

    def setUp(self):
        self.user = self._user('expire_user')

    def _setup_approved_driver_expired_license(self):
        """Identity approved, driver approved, license already expired."""
        self._approve_identity(self.user)
        past = date.today() - timedelta(days=1)
        req = driver_svc.submit_driver_verification(
            self.user, 'DL-EXP', past,
            _fake('n2.jpg'), _fake('dl2.jpg'),
        )
        driver_svc.approve(req)
        req.refresh_from_db()
        return req

    def test_expired_license_suspends_driver_verification(self):
        req = self._setup_approved_driver_expired_license()
        scan_expiring_documents()
        req.refresh_from_db()
        self.assertEqual(req.status, DriverVerification.Status.SUSPENDED)

    def test_expired_license_resets_driver_verification_status(self):
        self._setup_approved_driver_expired_license()
        scan_expiring_documents()
        driver = Driver.objects.get(user=self.user)
        self.assertNotEqual(driver.verification_status, Driver.VerificationStatus.VERIFIED)

    def test_expired_doc_sends_expiry_notification(self):
        self._setup_approved_driver_expired_license()
        scan_expiring_documents()
        self.assertTrue(
            Notification.objects.filter(
                user=self.user, type=Notification.Type.REVERIFICATION,
            ).exists()
        )

    def test_qr_denied_after_suspension(self):
        req = self._setup_approved_driver_expired_license()
        scan_expiring_documents()
        req.refresh_from_db()
        self.assertFalse(req.can_operate)

    def test_soon_to_expire_sends_reminder_not_suspension(self):
        """A doc expiring within VERIFICATION_REMINDER_DAYS triggers a reminder only."""
        self._approve_identity(self.user)
        soon = date.today() + timedelta(days=15)
        req = driver_svc.submit_driver_verification(
            self.user, 'DL-SOON', soon,
            _fake('n3.jpg'), _fake('dl3.jpg'),
        )
        driver_svc.approve(req)
        scan_expiring_documents()
        # reminder notification created
        self.assertTrue(
            Notification.objects.filter(
                user=self.user, type=Notification.Type.REVERIFICATION,
            ).exists()
        )
        # but the verification is NOT suspended
        req.refresh_from_db()
        self.assertEqual(req.status, DriverVerification.Status.APPROVED)


# ─── Story 12: trust score calculation ────────────────────────────────────────

class TrustScoreTest(_Base):
    """Factor weights are accumulated correctly at each verification milestone."""

    def setUp(self):
        self.user = self._user('scorer')

    def test_fresh_user_score(self):
        # No identity, no driver, no expired docs → documents_valid=True earns 20 pts.
        result = trust_compute(self.user)
        self.assertEqual(result['score'], 20)
        self.assertEqual(result['factors']['identity_verified'], 0)
        self.assertEqual(result['factors']['driver_verified'], 0)

    def test_identity_approval_raises_score(self):
        self._approve_identity(self.user)
        result = trust_compute(self.user)
        self.assertGreater(result['score'], 20)
        self.assertGreater(result['factors']['identity_verified'], 0)

    def test_driver_approval_raises_score_further(self):
        self._approve_identity(self.user)
        score_after_identity = trust_compute(self.user)['score']
        self._approve_driver(self.user)
        self.assertGreater(trust_compute(self.user)['score'], score_after_identity)
        self.assertGreater(trust_compute(self.user)['factors']['driver_verified'], 0)

    def test_verified_vehicle_adds_vehicle_factor(self):
        self._approve_identity(self.user)
        score_before = trust_compute(self.user)['score']
        Vehicle.objects.create(
            owner=self.user, registration_number='VHC-SCORE',
            vehicle_type='CAR', brand='Ford', model='Focus', year=2019,
            is_verified=True,
        )
        result = trust_compute(self.user)
        self.assertGreater(result['score'], score_before)
        self.assertGreater(result['factors']['vehicle_verified'], 0)

    def test_expired_document_zeroes_documents_valid_factor(self):
        req = self._approve_identity(self.user)
        # Add an expired doc under the same identity request
        ver_svc.attach_document(
            req, self.user, VerificationDocument.DocType.DRIVER_LICENSE,
            _fake('old_dl.jpg'),
            expiry_date=date.today() - timedelta(days=1),
        )
        result = trust_compute(self.user)
        self.assertEqual(result['factors']['documents_valid'], 0)

    def test_recompute_and_store_persists_on_user(self):
        from common.services.trust import recompute_and_store
        self._approve_identity(self.user)
        recompute_and_store(self.user)
        self.user.refresh_from_db()
        self.assertGreater(self.user.trust_score, 0)
