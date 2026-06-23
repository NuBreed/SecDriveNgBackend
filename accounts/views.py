from django.conf import settings
from django.contrib.auth import authenticate
from django.db.models import Q
from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, OpenApiResponse

from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenRefreshView
from rest_framework_simplejwt.token_blacklist.models import (
    OutstandingToken,
    BlacklistedToken,
)

from accounts.models import User, OTP, Device, AuthEvent
from accounts.serializers import (
    RegisterSerializer,
    VerifyOTPSerializer,
    ResendOTPSerializer,
    LoginSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    ChangePasswordSerializer,
    GoogleAuthSerializer,
    DeviceSerializer,
    AuthEventSerializer,
    UserProfileSerializer,
    _unique_username,
)
from accounts.services import otp_service, auth_events, tokens
from integrations.services.isafepass_bridge import get_bridge, ISafePassUnavailable


def resolve_user(identifier):
    """Find a user by email or phone."""
    if not identifier:
        return None
    identifier = identifier.strip()
    return User.objects.filter(
        Q(email__iexact=identifier) | Q(phone=identifier)
    ).first()


# ── Create account ──────────────────────────────────────────

class RegisterAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'otp'

    @extend_schema(request=RegisterSerializer, responses=UserProfileSerializer)
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        _, dev_code = otp_service.issue_and_send(user, OTP.Purpose.ACCOUNT_VERIFICATION)
        auth_events.log_event(
            AuthEvent.Type.REGISTER, user=user, request=request, identifier=user.email,
        )

        body = {
            'detail': 'Account created. Enter the code sent to your phone to activate it.',
            'user': UserProfileSerializer(user).data,
        }
        if dev_code is not None:
            body['dev_otp'] = dev_code
        return Response(body, status=status.HTTP_201_CREATED)


# ── Story 2: Verify account ──────────────────────────────────────────

class VerifyOTPAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'otp'

    @extend_schema(request=VerifyOTPSerializer, responses=UserProfileSerializer)
    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = resolve_user(serializer.validated_data['identifier'])
        if user is None:
            return Response({'detail': 'Invalid code.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            otp_service.verify(
                user, OTP.Purpose.ACCOUNT_VERIFICATION, serializer.validated_data['code'],
            )
        except otp_service.OTPError as exc:
            auth_events.log_event(
                AuthEvent.Type.OTP_VERIFY_FAILED, user=user, request=request,
            )
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        user.is_active = True
        user.is_verified = True
        # Phone + email confirmed → Level 1 basic verification (KYC epic).
        if user.verification_level < User.VerificationLevel.BASIC:
            user.verification_level = User.VerificationLevel.BASIC
        user.save(update_fields=['is_active', 'is_verified', 'verification_level'])
        auth_events.log_event(AuthEvent.Type.VERIFY, user=user, request=request)

        if user.email:
            try:
                from notifications.email import send_welcome
                send_welcome(user)
            except Exception:
                pass

        return Response({
            'detail': 'Account verified.',
            'user': UserProfileSerializer(user).data,
            **tokens.issue_tokens(user),
        })


class ResendOTPAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'otp'

    @extend_schema(request=ResendOTPSerializer, responses=OpenApiResponse(description='Code resent.'))
    def post(self, request):
        serializer = ResendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = resolve_user(serializer.validated_data['identifier'])
        # Don't reveal whether the account exists.
        if user is None:
            return Response({'detail': 'If that account exists, a new code has been sent.'})

        ok, wait = otp_service.can_resend(user, OTP.Purpose.ACCOUNT_VERIFICATION)
        if not ok:
            return Response(
                {'detail': f'Please wait {wait}s before requesting another code.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        _, dev_code = otp_service.issue_and_send(user, OTP.Purpose.ACCOUNT_VERIFICATION)
        body = {'detail': 'A new code has been sent.'}
        if dev_code is not None:
            body['dev_otp'] = dev_code
        return Response(body)


# ── Story 3: Login with email or phone ───────────────────────────────

class LoginAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'login'

    @extend_schema(request=LoginSerializer, responses=UserProfileSerializer)
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        identifier = vd['identifier'].strip()

        user = resolve_user(identifier)

        if user and user.is_locked_out:
            return Response(
                {'detail': 'Account temporarily locked due to failed login attempts. Try again later.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        authed = authenticate(request, username=identifier, password=vd['password'])

        if authed is None:
            auth_events.record_failed_login(user, request=request, identifier=identifier)
            return Response(
                {'detail': 'Invalid credentials.'}, status=status.HTTP_401_UNAUTHORIZED,
            )

        if not authed.is_active:
            return Response(
                {'detail': 'Account not verified. Please verify your account first.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        auth_events.clear_failures(authed)
        device = auth_events.register_device(authed, request=request, payload=vd)
        auth_events.log_event(
            AuthEvent.Type.LOGIN, user=authed, request=request,
            device_id=(device.device_id if device else ''),
        )

        return Response({
            'user': UserProfileSerializer(authed).data,
            **tokens.issue_tokens(authed),
        })


# ── Story 7: Refresh token ───────────────────────────────────────────

class SecDriveTokenRefreshView(TokenRefreshView):
    """SimpleJWT refresh + abuse monitoring."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        if response.status_code == status.HTTP_200_OK:
            user = request.user if request.user.is_authenticated else None
            auth_events.log_event(AuthEvent.Type.REFRESH, user=user, request=request)
        return response


# ── Story 8: Logout ──────────────────────────────────────────────────

class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request={'application/json': {'type': 'object', 'properties': {
            'refresh': {'type': 'string'}, 'device_id': {'type': 'string'}}}},
        responses=OpenApiResponse(description='Logged out.'),
    )
    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response({'detail': 'refresh is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            RefreshToken(refresh_token).blacklist()
        except TokenError:
            return Response({'detail': 'Invalid or expired token.'}, status=status.HTTP_400_BAD_REQUEST)

        device_id = (request.data.get('device_id') or '').strip()
        if device_id:
            auth_events.revoke_device(request.user, device_id)

        auth_events.log_event(
            AuthEvent.Type.LOGOUT, user=request.user, request=request, device_id=device_id,
        )
        return Response({'detail': 'Logged out successfully.'})


# ── Story 9: Forgot / reset password ─────────────────────────────────

class ForgotPasswordAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'otp'

    @extend_schema(request=ForgotPasswordSerializer, responses=OpenApiResponse(description='Reset code sent.'))
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = resolve_user(serializer.validated_data['identifier'])
        # Avoid user enumeration.
        if user is None:
            return Response({'detail': 'If that account exists, a reset code has been sent.'})

        _, dev_code = otp_service.issue_and_send(user, OTP.Purpose.PASSWORD_RESET)
        body = {'detail': 'A reset code has been sent.'}
        if dev_code is not None:
            body['dev_otp'] = dev_code
        return Response(body)


class ResetPasswordAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'otp'

    @extend_schema(request=ResetPasswordSerializer, responses=OpenApiResponse(description='Password reset.'))
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data

        user = resolve_user(vd['identifier'])
        if user is None:
            return Response({'detail': 'Invalid code.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            otp_service.verify(user, OTP.Purpose.PASSWORD_RESET, vd['code'])
        except otp_service.OTPError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(vd['new_password'])
        user.save(update_fields=['password'])

        # Revoke all existing sessions after a password reset.
        tokens.revoke_all_sessions(user)
        auth_events.clear_failures(user)
        auth_events.log_event(AuthEvent.Type.PASSWORD_RESET, user=user, request=request)

        if user.email:
            try:
                from notifications.email import send_password_changed
                send_password_changed(user)
            except Exception:
                pass

        return Response({'detail': 'Password reset successfully. Please log in again.'})


class ChangePasswordAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ChangePasswordSerializer, responses=OpenApiResponse(description='Password changed.'))
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data

        if not request.user.check_password(vd['current_password']):
            return Response({'detail': 'Current password is incorrect.'}, status=status.HTTP_400_BAD_REQUEST)

        request.user.set_password(vd['new_password'])
        request.user.save(update_fields=['password'])

        if request.user.email:
            try:
                from notifications.email import send_password_changed
                send_password_changed(request.user)
            except Exception:
                pass

        return Response({'detail': 'Password changed successfully.'})


# ── Story 4: Continue with Google ────────────────────────────────────

class GoogleAuthAPIView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = 'login'

    @extend_schema(request=GoogleAuthSerializer, responses=UserProfileSerializer)
    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data

        try:
            from google.oauth2 import id_token as google_id_token
            from google.auth.transport import requests as google_requests
            claims = google_id_token.verify_oauth2_token(
                vd['id_token'], google_requests.Request()
            )
        except Exception:
            return Response({'detail': 'Invalid or expired Google token.'}, status=status.HTTP_401_UNAUTHORIZED)

        if claims.get('iss') not in ('accounts.google.com', 'https://accounts.google.com'):
            return Response({'detail': 'Invalid token issuer.'}, status=status.HTTP_401_UNAUTHORIZED)

        allowed = getattr(settings, 'GOOGLE_OAUTH_CLIENT_IDS', [])
        if allowed and claims.get('aud') not in allowed:
            return Response({'detail': 'Token audience mismatch.'}, status=status.HTTP_401_UNAUTHORIZED)

        email = (claims.get('email') or '').strip().lower()
        if not email or not claims.get('email_verified', False):
            return Response(
                {'detail': 'Google account email is missing or unverified.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(email__iexact=email).first()
        created = False
        if user is None:
            user = User.objects.create(
                username=_unique_username(email),
                email=email,
                first_name=claims.get('given_name', '') or '',
                last_name=claims.get('family_name', '') or '',
                role=User.Roles.PASSENGER,
                is_active=True,
                is_verified=True,
                google_linked=True,
            )
            user.set_unusable_password()
            user.save()
            created = True
        elif not user.google_linked:
            user.google_linked = True
            user.save(update_fields=['google_linked'])

        device = auth_events.register_device(user, request=request, payload=vd)
        auth_events.log_event(
            AuthEvent.Type.LOGIN, user=user, request=request,
            device_id=(device.device_id if device else ''), method='google',
        )

        return Response({
            'user': UserProfileSerializer(user).data,
            'is_new': created,
            'needs_phone': not bool(user.phone),
            **tokens.issue_tokens(user),
        })


# ── Stories 5 & 6: Continue with / connect iSafePass ─────────────────

def _apply_isafepass_identity(user, payload):
    """Create or update the ISafePassLink with the bridge payload snapshot."""
    from accounts.models import ISafePassLink

    snapshot = {
        'emergency_contacts': payload.get('emergency_contacts', []),
        'safety_profile': payload.get('safety_profile', {}),
        'trust_network': payload.get('trust_network', []),
    }
    link, _ = ISafePassLink.objects.update_or_create(
        user=user,
        defaults={
            'isafepass_user_id': str(payload.get('isafepass_user_id', '')),
            'profile_snapshot': snapshot,
        },
    )
    return link


class ISafePassLoginAPIView(APIView):
    """GET /isafepass/login/ — begin the iSafePass SSO flow.

    With the trusted-bridge model there is no external redirect; the client
    obtains an iSafePass credential and posts it to the callback. This endpoint
    reports whether the integration is available.
    """
    permission_classes = [AllowAny]

    @extend_schema(responses=OpenApiResponse(description='SSO availability / callback info.'))
    def get(self, request):
        bridge = get_bridge()
        if not bridge.enabled:
            return Response(
                {'detail': 'iSafePass integration not configured.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response({
            'detail': 'Submit your iSafePass credential to the callback endpoint.',
            'callback': '/api/v1/auth/isafepass/callback/',
        })


class ISafePassCallbackAPIView(APIView):
    """GET/POST /isafepass/callback/ — verify the iSafePass credential, then
    create or link a SecDrive account and issue tokens."""
    permission_classes = [AllowAny]

    @extend_schema(responses=UserProfileSerializer)
    def get(self, request):
        return self._handle(request, request.query_params.get('credential'))

    @extend_schema(
        request={'application/json': {'type': 'object', 'properties': {
            'credential': {'type': 'string'}}}},
        responses=UserProfileSerializer,
    )
    def post(self, request):
        return self._handle(request, request.data.get('credential'))

    def _handle(self, request, credential):
        if not credential:
            return Response({'detail': 'credential is required.'}, status=status.HTTP_400_BAD_REQUEST)

        bridge = get_bridge()
        try:
            payload = bridge.verify_and_fetch(credential)
        except ISafePassUnavailable as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        email = (payload.get('email') or '').strip().lower()
        isafepass_id = str(payload.get('isafepass_user_id', ''))
        if not isafepass_id:
            return Response({'detail': 'iSafePass did not return an identity.'}, status=status.HTTP_502_BAD_GATEWAY)

        from accounts.models import ISafePassLink
        link = ISafePassLink.objects.filter(isafepass_user_id=isafepass_id).first()
        user = link.user if link else (User.objects.filter(email__iexact=email).first() if email else None)
        created = False
        if user is None:
            user = User.objects.create(
                username=_unique_username(email or f'isafepass_{isafepass_id}'),
                email=email or f'isafepass_{isafepass_id}@secdrive.local',
                phone=payload.get('phone') or None,
                first_name=payload.get('first_name', '') or '',
                last_name=payload.get('last_name', '') or '',
                role=User.Roles.PASSENGER,
                is_active=True,
                is_verified=True,
            )
            user.set_unusable_password()
            user.save()
            created = True

        _apply_isafepass_identity(user, payload)
        device = auth_events.register_device(user, request=request, payload=request.data)
        auth_events.log_event(
            AuthEvent.Type.LOGIN, user=user, request=request,
            device_id=(device.device_id if device else ''), method='isafepass',
        )

        return Response({
            'user': UserProfileSerializer(user).data,
            'is_new': created,
            **tokens.issue_tokens(user),
        })


class ISafePassSSOAPIView(APIView):
    """POST /isafepass/sso/ — one-shot SSO: email+password → SecDrive JWT.

    The app posts the user's iSafePass credentials here. SecDrive fetches an
    iSafePass access token on the user's behalf, verifies it via the bridge,
    then creates or links a SecDrive account and issues SecDrive tokens.
    The user never has to know about the bridge handshake.
    """
    permission_classes = [AllowAny]
    throttle_scope = 'auth'

    @extend_schema(
        request={'application/json': {'type': 'object', 'properties': {
            'email': {'type': 'string'},
            'password': {'type': 'string'},
        }, 'required': ['email', 'password']}},
        responses=UserProfileSerializer,
    )
    def post(self, request):
        email    = (request.data.get('email') or '').strip()
        password = (request.data.get('password') or '').strip()
        if not email or not password:
            return Response(
                {'detail': 'email and password are required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        bridge = get_bridge()
        try:
            credential = bridge.get_token(email, password)
        except ISafePassUnavailable as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        # Reuse the callback handler — it verifies credential, links user, issues tokens.
        return ISafePassCallbackAPIView()._handle(request, credential)


class ISafePassLinkAPIView(APIView):
    """POST /isafepass/link/ — connect an existing SecDrive account to iSafePass.

    Accepts either:
      • {"credential": "<isafepass-token>"}  — raw token (app-to-app flow)
      • {"email": "...", "password": "..."}  — driver enters iSafePass creds;
        backend fetches the token on their behalf (preferred mobile flow)
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request={'application/json': {'type': 'object', 'properties': {
            'credential': {'type': 'string'},
            'email':      {'type': 'string'},
            'password':   {'type': 'string'},
        }}},
        responses=OpenApiResponse(description='Account linked.'),
    )
    def post(self, request):
        from accounts.models import ISafePassLink

        credential = request.data.get('credential')
        bridge = get_bridge()

        # Driver-friendly flow: exchange email+password for a credential token
        # on the server side so the raw iSafePass token never travels to the client.
        if not credential:
            email    = (request.data.get('email') or '').strip()
            password = (request.data.get('password') or '').strip()
            if not email or not password:
                return Response(
                    {'detail': 'Provide either a credential token or your iSafePass email and password.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            try:
                credential = bridge.get_token(email, password)
            except ISafePassUnavailable as exc:
                return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            payload = bridge.link_account(request.user, credential)
        except ISafePassUnavailable as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        isafepass_id = str(payload.get('isafepass_user_id', ''))
        if not isafepass_id:
            return Response({'detail': 'iSafePass did not return an identity.'}, status=status.HTTP_502_BAD_GATEWAY)

        # Prevent linking an iSafePass account already tied to another user.
        existing = (
            ISafePassLink.objects
            .filter(isafepass_user_id=isafepass_id)
            .exclude(user=request.user)
            .first()
        )
        if existing:
            return Response(
                {'detail': 'This iSafePass account is already linked to another SecDrive user.'},
                status=status.HTTP_409_CONFLICT,
            )

        _apply_isafepass_identity(request.user, payload)
        request.user.refresh_from_db()
        return Response({
            'detail': 'iSafePass account linked.',
            'isafepass_linked': True,
            'user': UserProfileSerializer(request.user).data,
        })


# ── Story 10: Device registration ────────────────────────────────────

class DevicesAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=DeviceSerializer(many=True))
    def get(self, request):
        devices = request.user.devices.all()
        return Response(DeviceSerializer(devices, many=True).data)

    @extend_schema(request=DeviceSerializer, responses=DeviceSerializer)
    def post(self, request):
        serializer = DeviceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device = auth_events.register_device(
            request.user, request=request, payload=serializer.validated_data,
        )
        if device is None:
            return Response({'detail': 'device_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response(DeviceSerializer(device).data, status=status.HTTP_201_CREATED)


# ── Dashboard: profile, sessions, login history ───────────

class MeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=UserProfileSerializer)
    def get(self, request):
        return Response(UserProfileSerializer(request.user).data)


class SessionsAPIView(APIView):
    """Active (non-blacklisted, unexpired) refresh tokens for the user."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=OpenApiResponse(description='Active sessions.'))
    def get(self, request):
        blacklisted_ids = BlacklistedToken.objects.values_list('token_id', flat=True)
        active = (
            OutstandingToken.objects
            .filter(user=request.user, expires_at__gt=timezone.now())
            .exclude(id__in=blacklisted_ids)
            .order_by('-created_at')
        )
        data = [
            {
                'id':         t.id,
                'jti':        t.jti,
                'created_at': t.created_at,
                'expires_at': t.expires_at,
            }
            for t in active
        ]
        return Response(data)


class SessionRevokeView(APIView):
    """DELETE /api/v1/auth/sessions/{id}/  — revoke a specific session."""
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        try:
            token = OutstandingToken.objects.get(id=pk, user=request.user)
        except OutstandingToken.DoesNotExist:
            return Response({'detail': 'Session not found.'}, status=status.HTTP_404_NOT_FOUND)
        BlacklistedToken.objects.get_or_create(token=token)
        return Response({'detail': 'Session revoked.'}, status=status.HTTP_200_OK)


class LoginHistoryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=AuthEventSerializer(many=True))
    def get(self, request):
        events = request.user.auth_events.all()[:100]
        return Response(AuthEventSerializer(events, many=True).data)
