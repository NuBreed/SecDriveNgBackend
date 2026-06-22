from django.http import HttpResponse
from django.db.models import Q

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
    DriverListSerializer,
)
from drivers import services
from kyc.services import qr_service
from qr_codes import services as qr_code_services


class DriverSearchView(APIView):
    """GET /api/v1/drivers/search/

    Query params:
      q           — name / license / plate search
      vehicle_type — TAXI_DRIVER | OKADA_RIDER | KEKE_RIDER | BUS_DRIVER | SHUTTLE_DRIVER | DELIVERY_RIDER
      verified    — true | false (default: true)
      state       — e.g. Lagos
      page        — 1-based (default 1)
      page_size   — max 50 (default 20)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from drivers.models import Driver

        q            = (request.query_params.get('q') or '').strip()
        vehicle_type = (request.query_params.get('vehicle_type') or '').strip().upper()
        verified_param = request.query_params.get('verified', 'true').lower()
        state        = (request.query_params.get('state') or '').strip()
        try:
            page      = max(1, int(request.query_params.get('page', 1)))
            page_size = min(50, max(1, int(request.query_params.get('page_size', 20))))
        except (ValueError, TypeError):
            page, page_size = 1, 20

        qs = Driver.objects.select_related(
            'user', 'verification'
        ).order_by('-trust_score', '-created_at')

        # Verified filter
        if verified_param == 'true':
            qs = qs.filter(verification__status='APPROVED')

        # Vehicle type filter
        if vehicle_type:
            qs = qs.filter(participant_type=vehicle_type)

        # State filter
        if state:
            qs = qs.filter(user__state__icontains=state)

        # Text search — name, license, phone
        if q:
            qs = qs.filter(
                Q(user__first_name__icontains=q) |
                Q(user__last_name__icontains=q) |
                Q(license_number__icontains=q) |
                Q(user__phone_number__icontains=q)
            )

        total    = qs.count()
        offset   = (page - 1) * page_size
        drivers  = qs[offset: offset + page_size]
        has_more = (offset + page_size) < total

        serializer = DriverListSerializer(
            drivers, many=True, context={'request': request}
        )
        return Response({
            'results':   serializer.data,
            'total':     total,
            'page':      page,
            'page_size': page_size,
            'has_more':  has_more,
        })


class DriverDetailView(APIView):
    """GET /api/v1/drivers/<uuid:user_id>/"""
    permission_classes = [IsAuthenticated]

    def get(self, request, user_id):
        from drivers.models import Driver
        driver = Driver.objects.select_related(
            'user', 'verification'
        ).filter(user__uuid=user_id).first()
        if not driver:
            return Response({'detail': 'Driver not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(DriverListSerializer(driver, context={'request': request}).data)


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
