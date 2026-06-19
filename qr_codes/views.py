from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from qr_codes.models import QRCode, QRScan
from qr_codes import services as qr_services
from qr_codes.serializers import (
    QRCodeSerializer,
    QRScanSerializer,
    AssetQRGenerateSerializer,
    QRVerifySerializer,
    QRRevokeSerializer,
    QRRegenerateSerializer,
)
from kyc.services import qr_service


def _ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    return xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR')


class ParticipantQRGenerateView(APIView):
    """POST /api/v1/qr/participants/generate/ — Story 1."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={200: QRCodeSerializer},
        summary='Generate or retrieve the caller\'s participant QR code',
    )
    def post(self, request):
        try:
            qr = qr_services.get_or_create_participant_qr(request.user)
        except qr_services.QREligibilityError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_403_FORBIDDEN)
        if request.query_params.get('format') == 'png':
            return HttpResponse(qr_service.render_png(qr.token), content_type='image/png')
        return Response(
            {'qr': QRCodeSerializer(qr, context={'request': request}).data,
             'token': qr.token,
             'verify_url': qr_service.verify_url(qr.token)},
        )


class AssetQRGenerateView(APIView):
    """POST /api/v1/qr/assets/generate/ — Story 2."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=AssetQRGenerateSerializer,
        responses={200: QRCodeSerializer},
        summary='Generate or retrieve the asset QR code for a vehicle',
    )
    def post(self, request):
        ser = AssetQRGenerateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            qr = qr_services.get_or_create_asset_qr(request.user, ser.validated_data['vehicle_id'])
        except qr_services.QREligibilityError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_403_FORBIDDEN)
        if request.query_params.get('format') == 'png':
            return HttpResponse(qr_service.render_png(qr.token), content_type='image/png')
        return Response(
            {'qr': QRCodeSerializer(qr, context={'request': request}).data,
             'token': qr.token,
             'verify_url': qr_service.verify_url(qr.token)},
        )


class QRDetailView(APIView):
    """GET /api/v1/qr/{id}/ — Story 3."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=QRCodeSerializer, summary='Retrieve a QR code record by UUID')
    def get(self, request, pk):
        try:
            qr = QRCode.objects.get(id=pk)
        except QRCode.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        # Allow the entity owner or admin staff.
        entity = qr.content_object
        is_owner = (
            entity is not None and (
                (hasattr(entity, 'user') and entity.user == request.user) or
                (hasattr(entity, 'owner') and entity.owner == request.user)
            )
        )
        if not (is_owner or request.user.is_staff):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        return Response(QRCodeSerializer(qr, context={'request': request}).data)


class QRVerifyView(APIView):
    """POST /api/v1/qr/verify/ — Stories 4-7, 11-12."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=QRVerifySerializer,
        responses={200: OpenApiTypes.OBJECT},
        summary='Verify a participant and/or asset QR token, log the scan',
    )
    def post(self, request):
        ser = QRVerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        ua = request.META.get('HTTP_USER_AGENT', '')

        result = qr_services.verify_qr(
            d['token'], scanner=request.user, ip=_ip(request),
            user_agent=ua, latitude=d.get('latitude'), longitude=d.get('longitude'),
        )

        # Story 6 — combined verify: also check asset token if provided.
        asset_token = d.get('asset_token', '').strip()
        if asset_token:
            asset_result = qr_services.verify_qr(
                asset_token, scanner=request.user, ip=_ip(request),
                user_agent=ua, latitude=d.get('latitude'), longitude=d.get('longitude'),
            )
            result['asset'] = asset_result

        http_status = status.HTTP_200_OK if result.get('valid') else status.HTTP_400_BAD_REQUEST
        return Response(result, status=http_status)


class QRRevokeView(APIView):
    """POST /api/v1/qr/{id}/revoke/ — Story 8."""
    permission_classes = [IsAdminUser]

    @extend_schema(
        request=QRRevokeSerializer,
        responses={200: QRCodeSerializer},
        summary='Revoke a QR code (admin only)',
    )
    def post(self, request, pk):
        try:
            qr = QRCode.objects.get(id=pk)
        except QRCode.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        ser = QRRevokeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        qr = qr_services.revoke_qr(qr, admin=request.user, reason=ser.validated_data['reason'])
        return Response(QRCodeSerializer(qr, context={'request': request}).data)


class QRRegenerateView(APIView):
    """POST /api/v1/qr/{id}/regenerate/ — Story 9."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=QRRegenerateSerializer,
        responses={201: QRCodeSerializer},
        summary='Revoke and reissue a new QR code for the same entity',
    )
    def post(self, request, pk):
        try:
            qr = QRCode.objects.get(id=pk)
        except QRCode.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        # Only the entity owner or an admin may regenerate.
        entity = qr.content_object
        is_owner = (
            entity is not None and (
                (hasattr(entity, 'user') and entity.user == request.user) or
                (hasattr(entity, 'owner') and entity.owner == request.user)
            )
        )
        if not (is_owner or request.user.is_staff):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        ser = QRRegenerateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            new_qr = qr_services.regenerate_qr(
                qr, requester=request.user, reason=ser.validated_data['reason'],
            )
        except qr_services.QREligibilityError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_403_FORBIDDEN)
        return Response(
            QRCodeSerializer(new_qr, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )


class QRScanListView(APIView):
    """GET /api/v1/qr/scans/ — Story 10."""
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=QRScanSerializer(many=True),
        parameters=[
            OpenApiParameter('qr_id', OpenApiTypes.UUID, description='Filter by QR code UUID'),
            OpenApiParameter('result', OpenApiTypes.STR, description='Filter by scan result'),
        ],
        summary='List QR scan audit log entries (admin only)',
    )
    def get(self, request):
        qs = QRScan.objects.select_related('qr_code', 'scanned_by')
        if qr_id := request.query_params.get('qr_id'):
            qs = qs.filter(qr_code__id=qr_id)
        if result := request.query_params.get('result'):
            qs = qs.filter(result=result)
        return Response(QRScanSerializer(qs[:200], many=True).data)


class QRScanDetailView(APIView):
    """GET /api/v1/qr/scans/{id}/ — Story 10."""
    permission_classes = [IsAdminUser]

    @extend_schema(responses=QRScanSerializer, summary='Retrieve a single scan audit record (admin only)')
    def get(self, request, pk):
        try:
            scan = QRScan.objects.get(id=pk)
        except QRScan.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(QRScanSerializer(scan).data)
