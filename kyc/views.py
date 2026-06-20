from django.conf import settings

from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from common.services import badges as badge_svc
from kyc.models import IdentityVerification, VerificationStatus
from kyc.serializers import (
    IdentitySubmitSerializer,
    SelfieSerializer,
    IdentityVerificationSerializer,
)
from kyc.services import kyc_service


class IdentitySubmitView(APIView):
    """POST /api/v1/kyc/identity/ — submit identity documents (Story 1)."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request=IdentitySubmitSerializer, responses=IdentityVerificationSerializer)
    def post(self, request):
        serializer = IdentitySubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        req = kyc_service.submit_identity(
            request.user,
            primary_id_type=vd['primary_id_type'],
            id_document=vd['id_document'],
            document_number=vd.get('document_number', ''),
            selfie=vd.get('selfie'),
        )
        return Response(IdentityVerificationSerializer(req).data, status=status.HTTP_201_CREATED)


class SelfieView(APIView):
    """POST /api/v1/kyc/selfie/ — submit/replace selfie (Story 2)."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request=SelfieSerializer, responses=OpenApiResponse(description='Selfie submitted.'))
    def post(self, request):
        serializer = SelfieSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        kyc_service.attach_selfie(request.user, serializer.validated_data['selfie'])
        return Response({'detail': 'Selfie submitted for verification.'},
                        status=status.HTTP_201_CREATED)


class KYCStatusView(APIView):
    """GET /api/v1/kyc/status/ — verification dashboard (Story 10)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=OpenApiResponse(description='Verification dashboard summary.'))
    def get(self, request):
        user = request.user
        reminder_days = settings.VERIFICATION_REMINDER_DAYS

        identity = getattr(user, 'identity_verification', None)
        driver = getattr(user, 'driver', None)
        driver_v = getattr(driver, 'verification', None) if driver else None

        # Heal verification_level if identity was approved outside the service
        # (e.g. directly in Django admin) without updating the level field.
        if (
            identity is not None
            and identity.status == VerificationStatus.APPROVED
            and user.verification_level < user.VerificationLevel.IDENTITY
        ):
            user.verification_level = user.VerificationLevel.IDENTITY
            user.save(update_fields=['verification_level'])

        # Document expiry warnings across all of the user's documents.
        expiring = [
            {'doc_type': d.doc_type, 'expiry_date': d.expiry_date, 'expired': d.is_expired}
            for d in user.verification_documents.all()
            if d.expires_soon(reminder_days) or d.is_expired
        ]

        checks = {
            'phone_verified': bool(user.is_verified and user.phone),
            'email_verified': bool(user.is_verified and user.email),
            'identity_verified': user.verification_level >= user.VerificationLevel.IDENTITY,
            'driver_verified': bool(driver and driver.verification_status == 'VERIFIED'),
            'vehicle_verified': (
                user.vehicles_owned.filter(is_verified=True).exists()
                if hasattr(user, 'vehicles_owned') else False
            ),
        }

        return Response({
            'verification_level': user.verification_level,
            'verification_level_label': user.get_verification_level_display(),
            'checks': checks,
            'identity_status': identity.status if identity else VerificationStatus.NOT_SUBMITTED,
            'driver_status': driver_v.status if driver_v else VerificationStatus.NOT_SUBMITTED,
            'trust_score': user.trust_score,
            'badges': badge_svc.badges_for(user),
            'expiring_documents': expiring,
        })


class AdminQueueView(APIView):
    """GET /api/v1/kyc/admin/queue/?status=PENDING — KYC review queue."""
    permission_classes = [IsAdminUser]

    @extend_schema(parameters=[OpenApiParameter('status', str)],
                   responses=IdentityVerificationSerializer(many=True))
    def get(self, request):
        qs = IdentityVerification.objects.select_related('user').all()
        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter.upper())
        return Response(IdentityVerificationSerializer(qs, many=True).data)
