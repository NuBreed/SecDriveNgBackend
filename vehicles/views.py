from django.http import HttpResponse

from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema
from drf_spectacular.types import OpenApiTypes

from vehicles.models import Vehicle, VehicleVerification
from vehicles.serializers import (
    VehicleVerificationSubmitSerializer,
    VehicleVerificationSerializer,
)
from vehicles import services
from kyc.services import qr_service
from qr_codes import services as qr_code_services


class VehicleVerificationView(APIView):
    """POST /api/v1/vehicles/verification/ — register & submit a vehicle"""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request=VehicleVerificationSubmitSerializer, responses=VehicleVerificationSerializer)
    def post(self, request):
        serializer = VehicleVerificationSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        req = services.submit_vehicle_verification(
            request.user,
            vehicle_data=serializer.vehicle_data(),
            registration_doc=vd['registration_doc'],
            proof_of_ownership=vd['proof_of_ownership'],
            inspection_certificate=vd.get('inspection_certificate'),
            inspection_expiry=vd.get('inspection_expiry'),
            insurance=vd.get('insurance'),
            insurance_expiry=vd.get('insurance_expiry'),
        )
        return Response(VehicleVerificationSerializer(req).data, status=status.HTTP_201_CREATED)


class VehicleVerificationStatusView(APIView):
    """GET /api/v1/vehicles/verification/status/ — caller's vehicles."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=VehicleVerificationSerializer(many=True))
    def get(self, request):
        qs = VehicleVerification.objects.filter(owner=request.user).select_related('vehicle')
        return Response(VehicleVerificationSerializer(qs, many=True).data)


class VehicleQRView(APIView):
    """GET /api/v1/vehicles/<pk>/qr/ — QR for a verified vehicle with valid inspection."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.BINARY})
    def get(self, request, pk):
        vehicle = Vehicle.objects.filter(pk=pk, owner=request.user).first()
        req = getattr(vehicle, 'verification', None) if vehicle else None
        if vehicle is None:
            return Response({'detail': 'Vehicle not found.'}, status=status.HTTP_404_NOT_FOUND)
        if req is None or not req.is_road_eligible:
            return Response(
                {'detail': 'A QR code is only available for a verified vehicle with a valid inspection.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        qr = qr_code_services.get_or_create_asset_qr(request.user, vehicle.pk)
        if request.query_params.get('format') == 'json':
            return Response({'token': qr.token, 'verify_url': qr_service.verify_url(qr.token)})
        return HttpResponse(qr_service.render_png(qr.token), content_type='image/png')
