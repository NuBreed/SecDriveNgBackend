from datetime import timedelta

from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from rest_framework.test import APITestCase

from accounts.models import User, OTP, AuthEvent


# Use the console SMS backend so OTP codes are surfaced as dev_otp.
@override_settings(SMS_BACKEND='accounts.services.sms.ConsoleSMSBackend')
class AuthFlowTests(APITestCase):
    def _register(self, email='rider@example.com', phone='+2348010000001'):
        return self.client.post(reverse('accounts:register'), {
            'first_name': 'Ada',
            'last_name': 'Obi',
            'email': email,
            'phone': phone,
            'password': 'StrongPass123!',
        }, format='json')

    def test_register_creates_inactive_user_and_returns_dev_otp(self):
        resp = self._register()
        self.assertEqual(resp.status_code, 201)
        self.assertIn('dev_otp', resp.data)
        user = User.objects.get(email='rider@example.com')
        self.assertFalse(user.is_active)
        self.assertFalse(user.is_verified)
        self.assertEqual(user.role, User.Roles.PASSENGER)
        self.assertNotIn('access', resp.data)  # no tokens until verified

    def test_verify_activates_and_issues_tokens(self):
        otp = self._register().data['dev_otp']
        resp = self.client.post(reverse('accounts:verify-otp'), {
            'identifier': 'rider@example.com', 'code': otp,
        }, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)
        user = User.objects.get(email='rider@example.com')
        self.assertTrue(user.is_active and user.is_verified)

    def _register_and_verify(self, email='rider@example.com', phone='+2348010000001'):
        otp = self._register(email, phone).data['dev_otp']
        self.client.post(reverse('accounts:verify-otp'), {
            'identifier': email, 'code': otp,
        }, format='json')
        return User.objects.get(email=email)

    def test_login_with_email_and_with_phone(self):
        self._register_and_verify()
        for identifier in ('rider@example.com', '+2348010000001'):
            resp = self.client.post(reverse('accounts:login'), {
                'identifier': identifier, 'password': 'StrongPass123!',
                'device_id': 'dev-123', 'platform': 'android',
            }, format='json')
            self.assertEqual(resp.status_code, 200, identifier)
            self.assertIn('access', resp.data)
        # Device + login events recorded
        user = User.objects.get(email='rider@example.com')
        self.assertTrue(user.devices.filter(device_id='dev-123').exists())
        self.assertTrue(user.auth_events.filter(event_type=AuthEvent.Type.LOGIN).exists())

    def test_refresh_and_logout_blacklists_token(self):
        self._register_and_verify()
        login = self.client.post(reverse('accounts:login'), {
            'identifier': 'rider@example.com', 'password': 'StrongPass123!',
        }, format='json')
        access, refresh = login.data['access'], login.data['refresh']

        r = self.client.post(reverse('accounts:refresh'), {'refresh': refresh}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIn('access', r.data)

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')
        out = self.client.post(reverse('accounts:logout'), {'refresh': refresh}, format='json')
        self.assertEqual(out.status_code, 200)

        # Blacklisted refresh can no longer be used
        self.client.credentials()
        again = self.client.post(reverse('accounts:refresh'), {'refresh': refresh}, format='json')
        self.assertEqual(again.status_code, 401)

    def test_forgot_and_reset_password_revokes_sessions(self):
        self._register_and_verify()
        login = self.client.post(reverse('accounts:login'), {
            'identifier': 'rider@example.com', 'password': 'StrongPass123!',
        }, format='json')
        old_refresh = login.data['refresh']

        forgot = self.client.post(reverse('accounts:forgot-password'), {
            'identifier': 'rider@example.com',
        }, format='json')
        code = forgot.data['dev_otp']

        reset = self.client.post(reverse('accounts:reset-password'), {
            'identifier': 'rider@example.com', 'code': code, 'new_password': 'BrandNew456!',
        }, format='json')
        self.assertEqual(reset.status_code, 200)

        # Old sessions revoked
        again = self.client.post(reverse('accounts:refresh'), {'refresh': old_refresh}, format='json')
        self.assertEqual(again.status_code, 401)

        # New password works
        relogin = self.client.post(reverse('accounts:login'), {
            'identifier': 'rider@example.com', 'password': 'BrandNew456!',
        }, format='json')
        self.assertEqual(relogin.status_code, 200)

    def test_otp_expiry_rejected(self):
        otp = self._register().data['dev_otp']
        record = OTP.objects.get(user__email='rider@example.com', is_used=False)
        record.expires_at = timezone.now() - timedelta(minutes=1)
        record.save(update_fields=['expires_at'])
        resp = self.client.post(reverse('accounts:verify-otp'), {
            'identifier': 'rider@example.com', 'code': otp,
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_otp_max_attempts(self):
        self._register()
        with override_settings(OTP_MAX_ATTEMPTS=3):
            for _ in range(3):
                self.client.post(reverse('accounts:verify-otp'), {
                    'identifier': 'rider@example.com', 'code': '000000',
                }, format='json')
            resp = self.client.post(reverse('accounts:verify-otp'), {
                'identifier': 'rider@example.com', 'code': '000000',
            }, format='json')
            self.assertEqual(resp.status_code, 400)
            self.assertIn('request a new', resp.data['detail'].lower())

    @override_settings(LOGIN_MAX_FAILED_ATTEMPTS=3, LOGIN_LOCKOUT_MINUTES=15)
    def test_account_lockout_after_failed_logins(self):
        self._register_and_verify()
        for _ in range(3):
            self.client.post(reverse('accounts:login'), {
                'identifier': 'rider@example.com', 'password': 'wrong',
            }, format='json')
        user = User.objects.get(email='rider@example.com')
        self.assertTrue(user.is_locked_out)
        self.assertTrue(user.auth_events.filter(event_type=AuthEvent.Type.LOCKOUT).exists())

        # Even correct credentials are blocked while locked
        resp = self.client.post(reverse('accounts:login'), {
            'identifier': 'rider@example.com', 'password': 'StrongPass123!',
        }, format='json')
        self.assertEqual(resp.status_code, 403)


class RolePermissionTests(APITestCase):
    def test_driver_permission_blocks_passenger(self):
        from rest_framework.test import APIRequestFactory
        from rest_framework.views import APIView
        from rest_framework.response import Response
        from accounts.permissions import IsDriver

        class Probe(APIView):
            permission_classes = [IsDriver]

            def get(self, request):
                return Response({'ok': True})

        view = Probe.as_view()
        passenger = User.objects.create_user(
            username='p1', email='p1@example.com', password='x', role=User.Roles.PASSENGER,
        )
        driver = User.objects.create_user(
            username='d1', email='d1@example.com', password='x', role=User.Roles.DRIVER,
        )
        factory = APIRequestFactory()

        from rest_framework.test import force_authenticate
        req = factory.get('/probe/')
        force_authenticate(req, user=passenger)
        self.assertEqual(view(req).status_code, 403)

        req = factory.get('/probe/')
        force_authenticate(req, user=driver)
        self.assertEqual(view(req).status_code, 200)


class ISafePassDisabledTests(APITestCase):
    @override_settings(ISAFEPASS_BASE_URL='', ISAFEPASS_SERVICE_SECRET='')
    def test_isafepass_login_returns_503_when_unconfigured(self):
        resp = self.client.get(reverse('accounts:isafepass-login'))
        self.assertEqual(resp.status_code, 503)

    @override_settings(ISAFEPASS_BASE_URL='', ISAFEPASS_SERVICE_SECRET='')
    def test_isafepass_callback_returns_503_when_unconfigured(self):
        resp = self.client.post(reverse('accounts:isafepass-callback'), {
            'credential': 'anything',
        }, format='json')
        self.assertEqual(resp.status_code, 503)
