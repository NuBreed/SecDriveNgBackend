from django.http import HttpResponse

from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema
from drf_spectacular.types import OpenApiTypes

from drivers.serializers import (
    DriverVerificationSubmitSerializer,
    DriverVerificationSerializer,
)
from drivers import services
from kyc.services import qr_service
from qr_codes import services as qr_code_services


class DriverVerificationView(APIView):
    
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request=DriverVerificationSubmitSerializer, responses=DriverVerificationSerializer)
    def post(self, request):
        serializer = DriverVerificationSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        try:
            req = services.submit_driver_verification(
                request.user,
                license_number=vd['license_number'],
                license_expiry=vd['license_expiry'],
                national_id=vd['national_id'],
                driver_license=vd['driver_license'],
                passport_photo=vd.get('passport_photo'),
                selfie=vd.get('selfie'),
            )
        except services.VerificationError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response(DriverVerificationSerializer(req).data, status=status.HTTP_201_CREATED)


class DriverVerificationStatusView(APIView):
    
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=DriverVerificationSerializer)
    def get(self, request):
        driver = getattr(request.user, 'driver', None)
        req = getattr(driver, 'verification', None) if driver else None
        if req is None:
            return Response({'status': 'NOT_SUBMITTED'})
        return Response(DriverVerificationSerializer(req).data)


class DriverQRView(APIView):
    """GET /api/v1/drivers/qr/ — issue a QR only for a verified, valid driver (Story 8)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.BINARY})
    def get(self, request):
        driver = getattr(request.user, 'driver', None)
        req = getattr(driver, 'verification', None) if driver else None
        if req is None or not req.can_operate:
            return Response(
                {'detail': 'A QR code is only available to a verified driver with a valid license.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        qr = qr_code_services.get_or_create_participant_qr(request.user)
        if request.query_params.get('format') == 'json':
            return Response({'token': qr.token, 'verify_url': qr_service.verify_url(qr.token)})
        return HttpResponse(qr_service.render_png(qr.token), content_type='image/png')
