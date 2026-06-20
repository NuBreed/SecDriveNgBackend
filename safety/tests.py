"""
Tests for Epic 5 — Journey Sharing & Monitoring.

Stories covered:
  1-3  Manage trusted contacts (CRUD, relationship validation, flags)
  4    Select journey recipients (share with subset of contacts)
  5    Auto-share on journey start
  6    Generate live tracking link
  7    Subscribe journey to iSafePass (best-effort, graceful degradation)
  9    Live journey monitoring (public tracking endpoint)
  10   Journey event notifications
  12   Journey completion notification
  13   Privacy controls (per-share privacy settings)
  14   Shared journey dashboard (shared status endpoint)
"""
from datetime import date, timedelta

from django.test import TestCase
from rest_framework.test import APIClient

from accounts.models import User
from drivers.models import Driver, DriverVerification
from integrations.models import JourneySubscription
from journeys import sharing as sharing_svc
from journeys import services as journey_svc
from journeys.models import Journey, JourneyShare, TrackingLink
from notifications.models import Notification
from qr_codes import services as qr_svc
from safety.models import TrustedContact
from vehicles.models import Vehicle, VehicleVerification


# ─── helpers ──────────────────────────────────────────────────────────────────

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


def _verified_vehicle(user, reg='TST-001'):
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


def _journey(passenger, reg='SHR-001'):
    driver_user = _user('drvr_' + reg.replace('-', '_').lower())
    _verified_driver(driver_user)
    vehicle = _verified_vehicle(driver_user, reg=reg)
    p_qr = qr_svc.get_or_create_participant_qr(driver_user)
    a_qr = qr_svc.get_or_create_asset_qr(driver_user, vehicle.pk)
    return journey_svc.create_journey(passenger, p_qr.token, a_qr.token)


def _contact(owner, name='Alice', ctype=TrustedContact.ContactType.FAMILY,
             rel=TrustedContact.Relationship.SPOUSE, notify=True):
    return TrustedContact.objects.create(
        owner=owner, contact_type=ctype, relationship=rel,
        name=name, phone='+2348000000001',
        notify_on_journey=notify,
    )


# ─── Stories 1-3: Contact CRUD ────────────────────────────────────────────────

class TrustedContactCRUDTest(TestCase):
    def setUp(self):
        self.user = _user('passenger_c')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_create_family_contact(self):
        res = self.client.post('/api/v1/contacts/', {
            'contact_type': 'FAMILY', 'relationship': 'SPOUSE',
            'name': 'Jane Doe', 'phone': '+2348000000001',
        })
        self.assertEqual(res.status_code, 201)
        self.assertEqual(TrustedContact.objects.filter(owner=self.user).count(), 1)

    def test_family_contact_requires_relationship(self):
        res = self.client.post('/api/v1/contacts/', {
            'contact_type': 'FAMILY', 'name': 'Bob',
        })
        self.assertEqual(res.status_code, 400)

    def test_create_friend_contact_no_relationship_required(self):
        res = self.client.post('/api/v1/contacts/', {
            'contact_type': 'FRIEND', 'name': 'Charlie',
        })
        self.assertEqual(res.status_code, 201)

    def test_create_emergency_contact_with_primary_flag(self):
        res = self.client.post('/api/v1/contacts/', {
            'contact_type': 'EMERGENCY', 'name': 'Dr. Brown',
            'phone': '+2348000000002', 'is_primary_emergency': True,
        })
        self.assertEqual(res.status_code, 201)
        self.assertTrue(res.data['is_primary_emergency'])

    def test_list_contacts(self):
        _contact(self.user, name='A')
        _contact(self.user, name='B', ctype='FRIEND', rel='')
        res = self.client.get('/api/v1/contacts/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 2)

    def test_filter_by_type(self):
        _contact(self.user, name='Family', ctype='FAMILY', rel='PARENT')
        _contact(self.user, name='Friend', ctype='FRIEND', rel='')
        res = self.client.get('/api/v1/contacts/?type=FAMILY')
        self.assertEqual(len(res.data), 1)
        self.assertEqual(res.data[0]['name'], 'Family')

    def test_retrieve_contact(self):
        c = _contact(self.user)
        res = self.client.get(f'/api/v1/contacts/{c.id}/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['name'], c.name)

    def test_patch_contact(self):
        c = _contact(self.user)
        res = self.client.patch(f'/api/v1/contacts/{c.id}/', {'name': 'Updated Name'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['name'], 'Updated Name')

    def test_delete_contact(self):
        c = _contact(self.user)
        res = self.client.delete(f'/api/v1/contacts/{c.id}/')
        self.assertEqual(res.status_code, 204)
        self.assertFalse(TrustedContact.objects.filter(id=c.id).exists())

    def test_cannot_access_other_user_contact(self):
        other = _user('other_c')
        c = _contact(other)
        res = self.client.get(f'/api/v1/contacts/{c.id}/')
        self.assertEqual(res.status_code, 404)

    def test_cannot_patch_other_user_contact(self):
        other = _user('other_c2')
        c = _contact(other)
        res = self.client.patch(f'/api/v1/contacts/{c.id}/', {'name': 'Hacked'})
        self.assertEqual(res.status_code, 404)

    def test_unauthenticated_rejected(self):
        res = APIClient().get('/api/v1/contacts/')
        self.assertEqual(res.status_code, 401)

    def test_notify_on_journey_model_default_true(self):
        c = TrustedContact.objects.create(
            owner=self.user, contact_type='FRIEND', name='Default Notify',
        )
        self.assertTrue(c.notify_on_journey)

    def test_notify_on_journey_can_be_disabled(self):
        res = self.client.post('/api/v1/contacts/', {
            'contact_type': 'FRIEND', 'name': 'Silent Friend',
            'notify_on_journey': False,
        })
        self.assertEqual(res.status_code, 201)
        self.assertFalse(res.data['notify_on_journey'])


# ─── Story 4: Select journey recipients (share endpoint) ──────────────────────

class JourneyShareSelectRecipientsTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_s4')
        self.c1 = _contact(self.passenger, 'Mum')
        self.c2 = _contact(self.passenger, 'Dad', ctype='FRIEND', rel='')
        self.journey = _journey(self.passenger, reg='S4-001')
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_share_with_selected_contacts(self):
        res = self.client.post(
            f'/api/v1/journeys/{self.journey.id}/share/',
            {'contact_ids': [str(self.c1.id)]},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['shared_with'], 1)
        self.assertTrue(
            JourneyShare.objects.filter(journey=self.journey, contact=self.c1, active=True).exists()
        )

    def test_share_with_multiple_recipients(self):
        res = self.client.post(
            f'/api/v1/journeys/{self.journey.id}/share/',
            {'contact_ids': [str(self.c1.id), str(self.c2.id)]},
            format='json',
        )
        self.assertEqual(res.data['shared_with'], 2)

    def test_share_idempotent(self):
        self.client.post(
            f'/api/v1/journeys/{self.journey.id}/share/',
            {'contact_ids': [str(self.c1.id)]},
            format='json',
        )
        self.client.post(
            f'/api/v1/journeys/{self.journey.id}/share/',
            {'contact_ids': [str(self.c1.id)]},
            format='json',
        )
        self.assertEqual(
            JourneyShare.objects.filter(journey=self.journey, contact=self.c1).count(), 1
        )

    def test_empty_contact_ids_rejected(self):
        res = self.client.post(
            f'/api/v1/journeys/{self.journey.id}/share/',
            {'contact_ids': []},
            format='json',
        )
        self.assertEqual(res.status_code, 400)

    def test_cannot_share_other_user_journey(self):
        other = _user('interloper_s')
        c = APIClient()
        c.force_authenticate(other)
        res = c.post(
            f'/api/v1/journeys/{self.journey.id}/share/',
            {'contact_ids': [str(self.c1.id)]},
            format='json',
        )
        self.assertEqual(res.status_code, 403)

    def test_contact_from_other_user_silently_excluded(self):
        """Contacts belonging to another user are not included (not owned by passenger)."""
        other = _user('other_owner_s4')
        other_contact = _contact(other, 'Stranger')
        res = self.client.post(
            f'/api/v1/journeys/{self.journey.id}/share/',
            {'contact_ids': [str(other_contact.id)]},
            format='json',
        )
        self.assertEqual(res.data['shared_with'], 0)


# ─── Story 5: Auto-share on journey start ─────────────────────────────────────

class AutoShareOnJourneyStartTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_s5')
        self.contact_notified = _contact(self.passenger, 'Mum', notify=True)
        _contact(self.passenger, 'Silent', ctype='FRIEND', rel='', notify=False)

    def test_auto_share_includes_notify_contacts(self):
        journey = _journey(self.passenger, reg='S5-001')
        sharing_svc.on_journey_started(journey)
        self.assertTrue(
            JourneyShare.objects.filter(
                journey=journey, contact=self.contact_notified, active=True,
            ).exists()
        )

    def test_auto_share_excludes_silent_contacts(self):
        silent = TrustedContact.objects.get(name='Silent')
        journey = _journey(self.passenger, reg='S5-002')
        sharing_svc.on_journey_started(journey)
        self.assertFalse(
            JourneyShare.objects.filter(journey=journey, contact=silent).exists()
        )

    def test_notification_created_for_recipient(self):
        journey = _journey(self.passenger, reg='S5-003')
        sharing_svc.share_journey(journey, [str(self.contact_notified.id)])
        before = Notification.objects.count()
        sharing_svc.notify_recipients(journey, 'journey.started', {})
        self.assertEqual(Notification.objects.count(), before + 1)

    def test_notification_not_created_when_no_shares(self):
        journey = _journey(self.passenger, reg='S5-004')
        before = Notification.objects.count()
        sharing_svc.notify_recipients(journey, 'journey.started', {})
        self.assertEqual(Notification.objects.count(), before)


# ─── Story 6: Generate tracking link ──────────────────────────────────────────

class TrackingLinkTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_s6')
        self.journey = _journey(self.passenger, reg='S6-001')
        journey_svc.start_journey(self.journey, self.passenger)
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_create_tracking_link_via_api(self):
        res = self.client.post(f'/api/v1/journeys/{self.journey.id}/tracking-link/')
        self.assertEqual(res.status_code, 201)
        self.assertIn('token', res.data)
        self.assertIn('tracking_url', res.data)
        self.assertIn('expires_at', res.data)

    def test_tracking_link_record_created(self):
        self.client.post(f'/api/v1/journeys/{self.journey.id}/tracking-link/')
        self.assertEqual(TrackingLink.objects.filter(journey=self.journey).count(), 1)

    def test_public_tracking_endpoint_accessible_without_auth(self):
        link = sharing_svc.generate_tracking_link(self.journey, self.passenger)
        res = APIClient().get(f'/api/v1/tracking/{link.token}/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(str(res.data['journey_id']), str(self.journey.id))

    def test_public_tracking_returns_status(self):
        link = sharing_svc.generate_tracking_link(self.journey, self.passenger)
        res = APIClient().get(f'/api/v1/tracking/{link.token}/')
        self.assertEqual(res.data['status'], Journey.Status.ACTIVE)

    def test_public_tracking_returns_passenger_name(self):
        link = sharing_svc.generate_tracking_link(self.journey, self.passenger)
        res = APIClient().get(f'/api/v1/tracking/{link.token}/')
        self.assertIn('passenger_name', res.data)

    def test_invalid_token_returns_404(self):
        res = APIClient().get('/api/v1/tracking/completely-bogus-token/')
        self.assertEqual(res.status_code, 404)

    def test_deactivated_link_returns_404(self):
        link = sharing_svc.generate_tracking_link(self.journey, self.passenger)
        link.active = False
        link.save()
        res = APIClient().get(f'/api/v1/tracking/{link.token}/')
        self.assertEqual(res.status_code, 404)

    def test_service_generate_tracking_link_returns_link(self):
        link = sharing_svc.generate_tracking_link(self.journey, self.passenger, expires_hours=48)
        self.assertIsNotNone(link.token)
        self.assertNotEqual(link.token, '__placeholder__')


# ─── Story 7: iSafePass subscription (graceful degradation) ───────────────────

class ISafePassSubscriptionTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_s7')
        self.journey = _journey(self.passenger, reg='S7-001')

    def test_subscription_created_as_failed_when_bridge_unavailable(self):
        sharing_svc._subscribe_isafepass(self.journey)
        sub = JourneySubscription.objects.get(journey=self.journey)
        self.assertEqual(sub.status, JourneySubscription.Status.FAILED)

    def test_error_message_mentions_not_configured(self):
        sharing_svc._subscribe_isafepass(self.journey)
        sub = JourneySubscription.objects.get(journey=self.journey)
        self.assertIn('not configured', sub.error_message.lower())

    def test_subscribe_does_not_raise_when_bridge_unavailable(self):
        """Confirm the call is silent/best-effort — no exception propagates."""
        try:
            sharing_svc._subscribe_isafepass(self.journey)
        except Exception as exc:
            self.fail(f'_subscribe_isafepass raised unexpectedly: {exc}')

    def test_subscription_record_not_duplicated_on_second_call(self):
        sharing_svc._subscribe_isafepass(self.journey)
        sharing_svc._subscribe_isafepass(self.journey)
        self.assertEqual(JourneySubscription.objects.filter(journey=self.journey).count(), 1)

    def test_manual_subscribe_endpoint_returns_status(self):
        c = APIClient()
        c.force_authenticate(self.passenger)
        res = c.post('/api/v1/isafepass/subscribe/', {'journey_id': str(self.journey.id)})
        self.assertEqual(res.status_code, 200)
        self.assertIn('status', res.data)

    def test_manual_subscribe_wrong_journey_gets_404(self):
        import uuid
        c = APIClient()
        c.force_authenticate(self.passenger)
        res = c.post('/api/v1/isafepass/subscribe/', {'journey_id': str(uuid.uuid4())})
        self.assertEqual(res.status_code, 404)

    def test_manual_unsubscribe_endpoint_returns_200(self):
        c = APIClient()
        c.force_authenticate(self.passenger)
        res = c.post('/api/v1/isafepass/unsubscribe/', {'journey_id': str(self.journey.id)})
        self.assertEqual(res.status_code, 200)


# ─── Story 9: Public tracking / live monitoring ───────────────────────────────

class PublicTrackingViewTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_s9')
        self.journey = _journey(self.passenger, reg='S9-001')
        journey_svc.start_journey(self.journey, self.passenger)
        journey_svc.record_location(self.journey, 6.52, 3.37, speed=30.0)
        self.link = sharing_svc.generate_tracking_link(self.journey, self.passenger)

    def test_current_location_returned(self):
        res = APIClient().get(f'/api/v1/tracking/{self.link.token}/')
        self.assertEqual(res.status_code, 200)
        self.assertIsNotNone(res.data['current_location'])
        self.assertAlmostEqual(res.data['current_location']['lat'], 6.52)
        self.assertAlmostEqual(res.data['current_location']['lng'], 3.37)

    def test_no_location_returns_null(self):
        journey2 = _journey(self.passenger, reg='S9-002')
        journey_svc.start_journey(journey2, self.passenger)
        link2 = sharing_svc.generate_tracking_link(journey2, self.passenger)
        res = APIClient().get(f'/api/v1/tracking/{link2.token}/')
        self.assertIsNone(res.data['current_location'])

    def test_status_is_active(self):
        res = APIClient().get(f'/api/v1/tracking/{self.link.token}/')
        self.assertEqual(res.data['status'], Journey.Status.ACTIVE)


# ─── Story 10: Journey event notifications ────────────────────────────────────

class JourneyEventNotificationTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_s10')
        self.contact = _contact(self.passenger, 'Watcher')
        self.journey = _journey(self.passenger, reg='S10-001')
        sharing_svc.share_journey(self.journey, [str(self.contact.id)])

    def test_pause_event_creates_notification(self):
        journey_svc.start_journey(self.journey, self.passenger)
        before = Notification.objects.count()
        sharing_svc.on_journey_event(self.journey, 'journey.paused', {})
        self.assertGreater(Notification.objects.count(), before)

    def test_unknown_event_still_creates_notification(self):
        before = Notification.objects.count()
        sharing_svc.on_journey_event(self.journey, 'journey.alert', {'message': 'test'})
        self.assertGreater(Notification.objects.count(), before)


# ─── Story 12: Journey completion notification ────────────────────────────────

class JourneyCompletionNotificationTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_s12')
        self.contact = _contact(self.passenger, 'Tracker')
        self.journey = _journey(self.passenger, reg='S12-001')
        sharing_svc.share_journey(self.journey, [str(self.contact.id)])
        journey_svc.start_journey(self.journey, self.passenger)

    def test_completion_notification_sent(self):
        before = Notification.objects.count()
        sharing_svc.on_journey_event(self.journey, 'journey.completed', {
            'message': 'The journey has safely completed.',
        })
        self.assertEqual(Notification.objects.count(), before + 1)

    def test_notification_has_journey_completed_title(self):
        sharing_svc.on_journey_event(self.journey, 'journey.completed', {})
        notif = Notification.objects.filter(user=self.passenger).last()
        self.assertIn('completed', notif.title.lower())


# ─── Story 13: Privacy controls ───────────────────────────────────────────────

class PrivacyControlsTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_s13')
        self.contact = _contact(self.passenger, 'Privacy Friend', ctype='FRIEND', rel='')
        self.journey = _journey(self.passenger, reg='S13-001')

    def test_privacy_override_stored_on_share(self):
        sharing_svc.share_journey(
            self.journey, [str(self.contact.id)],
            privacy_overrides={str(self.contact.id): {'show_location': False}},
        )
        share = JourneyShare.objects.get(journey=self.journey, contact=self.contact)
        self.assertFalse(share.get_privacy()['show_location'])

    def test_default_privacy_shows_all(self):
        sharing_svc.share_journey(self.journey, [str(self.contact.id)])
        share = JourneyShare.objects.get(journey=self.journey, contact=self.contact)
        priv = share.get_privacy()
        self.assertTrue(priv['show_location'])
        self.assertTrue(priv['show_participant'])
        self.assertTrue(priv['show_asset'])

    def test_privacy_updated_on_re_share(self):
        sharing_svc.share_journey(self.journey, [str(self.contact.id)])
        sharing_svc.share_journey(
            self.journey, [str(self.contact.id)],
            privacy_overrides={str(self.contact.id): {'show_participant': False}},
        )
        share = JourneyShare.objects.get(journey=self.journey, contact=self.contact)
        self.assertFalse(share.get_privacy()['show_participant'])


# ─── Story 14: Shared journey dashboard ───────────────────────────────────────

class SharedStatusEndpointTest(TestCase):
    def setUp(self):
        self.passenger = _user('pax_s14')
        self.c1 = _contact(self.passenger, 'Watcher')
        self.journey = _journey(self.passenger, reg='S14-001')
        sharing_svc.share_journey(self.journey, [str(self.c1.id)])
        self.client = APIClient()
        self.client.force_authenticate(self.passenger)

    def test_shared_status_lists_active_recipients(self):
        res = self.client.get(f'/api/v1/journeys/{self.journey.id}/shared/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data['recipients']), 1)
        self.assertEqual(res.data['recipients'][0]['name'], 'Watcher')

    def test_unshare_removes_recipient_from_status(self):
        sharing_svc.unshare_journey(self.journey, [str(self.c1.id)])
        res = self.client.get(f'/api/v1/journeys/{self.journey.id}/shared/')
        self.assertEqual(len(res.data['recipients']), 0)

    def test_unshare_via_api_single(self):
        res = self.client.post(
            f'/api/v1/journeys/{self.journey.id}/unshare/',
            {'contact_ids': [str(self.c1.id)]},
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['unshared_from'], 1)

    def test_unshare_all_when_no_contact_ids_in_body(self):
        c2 = _contact(self.passenger, 'Watcher2', ctype='FRIEND', rel='')
        sharing_svc.share_journey(self.journey, [str(self.c1.id), str(c2.id)])
        res = self.client.post(
            f'/api/v1/journeys/{self.journey.id}/unshare/', {}, format='json',
        )
        self.assertEqual(res.data['unshared_from'], 2)

    def test_re_share_after_unshare_reactivates(self):
        sharing_svc.unshare_journey(self.journey, [str(self.c1.id)])
        sharing_svc.share_journey(self.journey, [str(self.c1.id)])
        share = JourneyShare.objects.get(journey=self.journey, contact=self.c1)
        self.assertTrue(share.active)

    def test_shared_status_includes_privacy(self):
        res = self.client.get(f'/api/v1/journeys/{self.journey.id}/shared/')
        recipient = res.data['recipients'][0]
        self.assertIn('privacy', recipient)

    def test_other_user_cannot_see_shared_status(self):
        other = _user('other_s14')
        c = APIClient()
        c.force_authenticate(other)
        res = c.get(f'/api/v1/journeys/{self.journey.id}/shared/')
        self.assertEqual(res.status_code, 403)
