"""Accident Detection & Emergency Escalation API views (Epic 7)."""
from rest_framework import status
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema
from drf_spectacular.types import OpenApiTypes

from accident_detection import services as ad_svc
from accident_detection.models import (
    AccidentEvent, DeliveryLog, EmergencyEscalation, SOSRequest,
)
from accident_detection.serializers import (
    AccidentConfirmSerializer, AccidentEventSerializer,
    DeliveryLogSerializer, EmergencyEscalationSerializer,
    SOSRequestSerializer, SOSTriggerSerializer, SensorDataSerializer,
)
from journeys.models import Journey


def _get_journey(pk, user):
    try:
        j = Journey.objects.get(id=pk)
    except Journey.DoesNotExist:
        return None, Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
    # Passenger OR the driver's user may trigger SOS/panic.
    is_participant = (
        j.passenger_id == user.pk
        or j.driver.user_id == user.pk
        or user.is_staff
    )
    if not is_participant:
        return None, Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
    return j, None


# ── Story 1-3: Sensor data ingestion ─────────────────────────────────────────

class SensorDataView(APIView):
    """POST /api/v1/journeys/{id}/sensor-data/

    Receives accelerometer / gyroscope / orientation readings from the mobile
    app and runs the accident-detection pipeline.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=SensorDataSerializer,
        responses={200: OpenApiTypes.OBJECT},
        summary='Submit sensor data for accident detection',
    )
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        if journey.status != Journey.Status.ACTIVE:
            return Response(
                {'detail': 'Sensor data is only accepted for active journeys.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ser = SensorDataSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        sensor = ser.validated_data

        last_location = journey.last_location
        events = ad_svc.process_sensor_data(journey, sensor, last_location)
        return Response({
            'events_detected': len(events),
            'event_ids': [str(e.id) for e in events],
        })


# ── Story 4: Passenger SOS ────────────────────────────────────────────────────

class SOSTriggerView(APIView):
    """POST /api/v1/journeys/{id}/sos/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=SOSTriggerSerializer,
        responses={201: SOSRequestSerializer},
        summary='Trigger a passenger SOS for an active journey',
    )
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        if journey.status != Journey.Status.ACTIVE:
            return Response(
                {'detail': 'SOS can only be triggered on an active journey.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ser = SOSTriggerSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        sos = ad_svc.trigger_sos(
            journey, request.user,
            lat=ser.validated_data.get('lat'),
            lng=ser.validated_data.get('lng'),
            message=ser.validated_data.get('message', ''),
        )
        return Response(SOSRequestSerializer(sos).data, status=status.HTTP_201_CREATED)


# ── Story 5: Driver / Rider Panic Button ──────────────────────────────────────

class PanicTriggerView(APIView):
    """POST /api/v1/journeys/{id}/panic/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=SOSTriggerSerializer,
        responses={201: SOSRequestSerializer},
        summary='Trigger a driver / rider panic button for an active journey',
    )
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        if journey.status != Journey.Status.ACTIVE:
            return Response(
                {'detail': 'Panic button can only be triggered on an active journey.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ser = SOSTriggerSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        sos = ad_svc.trigger_panic(
            journey, request.user,
            lat=ser.validated_data.get('lat'),
            lng=ser.validated_data.get('lng'),
            message=ser.validated_data.get('message', ''),
        )
        return Response(SOSRequestSerializer(sos).data, status=status.HTTP_201_CREATED)


# ── Story 6: Accident confirmation ────────────────────────────────────────────

class AccidentConfirmView(APIView):
    """POST /api/v1/journeys/{id}/accident-confirm/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=AccidentConfirmSerializer,
        responses={200: AccidentEventSerializer},
        summary='Passenger confirms their status after a possible-accident detection',
    )
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        ser = AccidentConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            event = AccidentEvent.objects.get(
                id=ser.validated_data['event_id'], journey=journey,
            )
        except AccidentEvent.DoesNotExist:
            return Response({'detail': 'Accident event not found.'},
                            status=status.HTTP_404_NOT_FOUND)
        updated = ad_svc.confirm_accident(event, request.user, ser.validated_data['response'])
        return Response(AccidentEventSerializer(updated).data)


# ── Story 11: Emergency timeline ──────────────────────────────────────────────

class EmergencyTimelineView(APIView):
    """GET /api/v1/journeys/{id}/emergency/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: OpenApiTypes.OBJECT},
        summary='Get the full emergency event timeline for a journey',
    )
    def get(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        return Response({
            'journey_id': str(journey.id),
            'timeline': ad_svc.get_emergency_timeline(journey),
        })


# ── Story 12: Delivery health / logs ─────────────────────────────────────────

class DeliveryHealthView(APIView):
    """GET /api/v1/journeys/{id}/emergency/delivery/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=EmergencyEscalationSerializer(many=True),
        summary='View escalation delivery status and retry logs for a journey',
    )
    def get(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        escalations = EmergencyEscalation.objects.filter(
            journey=journey,
        ).prefetch_related('delivery_logs').order_by('-created_at')
        data = []
        for esc in escalations:
            d = EmergencyEscalationSerializer(esc).data
            d['delivery_logs'] = DeliveryLogSerializer(
                esc.delivery_logs.all(), many=True,
            ).data
            data.append(d)
        return Response(data)


# ── Admin dashboard ───────────────────────────────────────────────────────────

class AdminActiveEmergenciesView(APIView):
    """GET /api/v1/admin/emergencies/ — active emergencies across all journeys."""
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses={200: OpenApiTypes.OBJECT},
        summary='List active emergencies and pending escalations (admin)',
    )
    def get(self, request):
        pending_events = AccidentEvent.objects.filter(
            confirmation_status=AccidentEvent.ConfirmationStatus.PENDING,
        ).select_related('journey__passenger').order_by('-detected_at')

        active_sos = SOSRequest.objects.exclude(
            status=SOSRequest.Status.DELIVERED,
        ).select_related('journey').order_by('-triggered_at')

        failed_escalations = EmergencyEscalation.objects.filter(
            status__in=[EmergencyEscalation.Status.FAILED, EmergencyEscalation.Status.RETRYING],
        ).select_related('journey').order_by('-created_at')

        return Response({
            'pending_accident_confirmations': AccidentEventSerializer(pending_events, many=True).data,
            'active_sos_requests': SOSRequestSerializer(active_sos, many=True).data,
            'failed_escalations': EmergencyEscalationSerializer(failed_escalations, many=True).data,
        })


class AdminEscalationLogsView(APIView):
    """GET /api/v1/admin/emergencies/logs/ — full delivery log for audit."""
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=DeliveryLogSerializer(many=True),
        summary='All emergency delivery logs (admin)',
    )
    def get(self, request):
        qs = DeliveryLog.objects.select_related('escalation__journey').order_by('-attempted_at')[:200]
        return Response(DeliveryLogSerializer(qs, many=True).data)
