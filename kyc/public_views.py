"""Public, unauthenticated QR scan-verify endpoint.

A passenger scans a driver/vehicle QR; this resolves the signed token and
returns the entity's current verification status, badges, and trust score. No
sensitive documents are exposed.
"""
from django.core import signing

from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, OpenApiResponse

from common.services import badges as badge_svc
from kyc.services import qr_service


class PublicVerifyView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses=OpenApiResponse(description='Verification summary for a scanned entity.'))
    def get(self, request, token):
        # Try v2 token first (persistent, revocable); fall back to v1 stateless.
        try:
            data = qr_service.read_token_v2(token)
            # v2 path: delegate to the full verify service (logs scan + checks revocation).
            from qr_codes import services as qr_code_services
            result = qr_code_services.verify_qr(token)
            return Response(result, status=status.HTTP_200_OK if result.get('valid') else status.HTTP_400_BAD_REQUEST)
        except signing.BadSignature:
            pass  # not a v2 token — try v1 below

        try:
            data = qr_service.read_token(token)
        except signing.BadSignature:
            return Response({'detail': 'Invalid or tampered code.'}, status=status.HTTP_400_BAD_REQUEST)

        entity_type, entity_id = data.get('t'), data.get('id')
        if entity_type == 'driver':
            return self._driver(entity_id)
        if entity_type == 'vehicle':
            return self._vehicle(entity_id)
        return Response({'detail': 'Unknown verification code.'}, status=status.HTTP_400_BAD_REQUEST)

    def _driver(self, driver_id):
        from drivers.models import Driver
        driver = Driver.objects.filter(pk=driver_id).select_related('user').first()
        if driver is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        req = getattr(driver, 'verification', None)
        user = driver.user
        return Response({
            'entity': 'driver',
            'name': f'{user.first_name} {user.last_name}'.strip() or user.username,
            'verified': bool(req and req.can_operate),
            'status': req.status if req else 'NOT_SUBMITTED',
            'license_valid': bool(req and not req.license_expired),
            'badges': badge_svc.badges_for(user),
            'trust_score': user.trust_score,
        })

    def _vehicle(self, vehicle_id):
        from vehicles.models import Vehicle
        vehicle = Vehicle.objects.filter(pk=vehicle_id).first()
        if vehicle is None:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        req = getattr(vehicle, 'verification', None)
        return Response({
            'entity': 'vehicle',
            'registration_number': vehicle.registration_number,
            'description': f'{vehicle.brand} {vehicle.model} ({vehicle.year})',
            'verified': bool(req and req.is_road_eligible),
            'status': req.status if req else 'NOT_SUBMITTED',
            'inspection_valid': bool(req and not req.inspection_expired),
            'badges': badge_svc.badges_for_vehicle(vehicle),
        })
