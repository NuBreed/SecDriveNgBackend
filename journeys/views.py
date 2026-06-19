from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from journeys.models import Journey, JourneyEvent, JourneyLocation
from journeys.serializers import (
    JourneySerializer,
    JourneyCreateSerializer,
    DestinationSerializer,
    PauseSerializer,
    CancelSerializer,
    JourneyEventSerializer,
    JourneyLocationSerializer,
    LocationUpdateSerializer,
)
from journeys import services


def _get_journey(pk, user):
    """Return Journey if user is passenger, driver.user, or staff."""
    try:
        j = Journey.objects.get(id=pk)
    except Journey.DoesNotExist:
        return None, Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
    if (j.passenger_id != user.pk
            and j.driver.user_id != user.pk
            and not user.is_staff):
        return None, Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
    return j, None


class JourneyListCreateView(APIView):
    """GET /api/v1/journeys/  POST /api/v1/journeys/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=JourneySerializer(many=True),
        parameters=[
            OpenApiParameter('status', OpenApiTypes.STR, description='Filter by journey status'),
        ],
        summary='List journeys for the current user',
    )
    def get(self, request):
        qs = Journey.objects.filter(passenger=request.user)
        if s := request.query_params.get('status'):
            qs = qs.filter(status=s.upper())
        return Response(JourneySerializer(qs, many=True).data)

    @extend_schema(
        request=JourneyCreateSerializer,
        responses={201: JourneySerializer},
        summary='Create a journey after verifying participant and asset QR tokens',
    )
    def post(self, request):
        ser = JourneyCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            journey = services.create_journey(
                passenger=request.user,
                participant_token=ser.validated_data['participant_token'],
                asset_token=ser.validated_data['asset_token'],
            )
        except services.JourneyError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(JourneySerializer(journey).data, status=status.HTTP_201_CREATED)


class JourneyDetailView(APIView):
    """GET /api/v1/journeys/{id}/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=JourneySerializer, summary='Retrieve a journey')
    def get(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        return Response(JourneySerializer(journey).data)


class JourneyDestinationView(APIView):
    """POST /api/v1/journeys/{id}/destination/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(request=DestinationSerializer, responses=JourneySerializer,
                   summary='Set or update destination')
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        ser = DestinationSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            journey = services.set_destination(
                journey, request.user,
                origin_lat=d['origin_lat'], origin_lng=d['origin_lng'],
                origin_address=d['origin_address'],
                dest_lat=d['destination_lat'], dest_lng=d['destination_lng'],
                dest_address=d['destination_address'],
                estimated_distance_m=d.get('estimated_distance_m'),
                estimated_duration_s=d.get('estimated_duration_s'),
            )
        except services.JourneyError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(JourneySerializer(journey).data)


class JourneyStartView(APIView):
    """POST /api/v1/journeys/{id}/start/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses=JourneySerializer, summary='Start a journey')
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        try:
            journey = services.start_journey(journey, request.user)
        except services.JourneyError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(JourneySerializer(journey).data)


class JourneyPauseView(APIView):
    """POST /api/v1/journeys/{id}/pause/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(request=PauseSerializer, responses=JourneySerializer, summary='Pause an active journey')
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        ser = PauseSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            journey = services.pause_journey(journey, request.user, ser.validated_data['reason'])
        except services.JourneyError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(JourneySerializer(journey).data)


class JourneyResumeView(APIView):
    """POST /api/v1/journeys/{id}/resume/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses=JourneySerializer, summary='Resume a paused journey')
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        try:
            journey = services.resume_journey(journey, request.user)
        except services.JourneyError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(JourneySerializer(journey).data)


class JourneyCompleteView(APIView):
    """POST /api/v1/journeys/{id}/complete/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses=JourneySerializer, summary='Complete a journey')
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        try:
            journey = services.complete_journey(journey, request.user)
        except services.JourneyError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(JourneySerializer(journey).data)


class JourneyCancelView(APIView):
    """POST /api/v1/journeys/{id}/cancel/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(request=CancelSerializer, responses=JourneySerializer, summary='Cancel a journey')
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        ser = CancelSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            journey = services.cancel_journey(journey, request.user, ser.validated_data['reason'])
        except services.JourneyError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(JourneySerializer(journey).data)


class JourneyLocationView(APIView):
    """POST /api/v1/journeys/{id}/locations/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=LocationUpdateSerializer,
        responses={201: JourneyLocationSerializer},
        summary='Record a GPS location update',
    )
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        ser = LocationUpdateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        try:
            loc = services.record_location(
                journey,
                latitude=d['latitude'], longitude=d['longitude'],
                speed=d.get('speed'), heading=d.get('heading'),
                accuracy=d.get('accuracy'), altitude=d.get('altitude'),
                client_timestamp=d.get('client_timestamp'),
            )
        except services.JourneyError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(JourneyLocationSerializer(loc).data, status=status.HTTP_201_CREATED)


class JourneyTimelineView(APIView):
    """GET /api/v1/journeys/{id}/timeline/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=JourneyEventSerializer(many=True), summary='Journey event timeline')
    def get(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        events = JourneyEvent.objects.filter(journey=journey).order_by('timestamp')
        return Response(JourneyEventSerializer(events, many=True).data)


class JourneyHistoryView(APIView):
    """GET /api/v1/journeys/history/  — completed/cancelled journeys (Story 14)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=JourneySerializer(many=True),
        summary='Passenger journey history (completed + cancelled)',
    )
    def get(self, request):
        qs = Journey.objects.filter(
            passenger=request.user,
            status__in=[Journey.Status.COMPLETED, Journey.Status.CANCELLED],
        )
        return Response(JourneySerializer(qs, many=True).data)


class ActiveJourneyView(APIView):
    """GET /api/v1/journeys/active/ — current active journey (Story 15)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=JourneySerializer(many=True), summary='Active journeys for current user')
    def get(self, request):
        qs = Journey.objects.filter(
            passenger=request.user,
            status__in=[Journey.Status.ACTIVE, Journey.Status.PAUSED],
        )
        return Response(JourneySerializer(qs, many=True).data)


# ── Admin views ────────────────────────────────────────────────────────────────

class AdminLiveJourneysView(APIView):
    """GET /api/v1/journeys/admin/live/ — all live journeys."""
    permission_classes = [IsAdminUser]

    @extend_schema(responses=JourneySerializer(many=True), summary='All live journeys (admin)')
    def get(self, request):
        qs = Journey.objects.filter(
            status__in=[Journey.Status.ACTIVE, Journey.Status.PAUSED, Journey.Status.INCIDENT],
        ).select_related('passenger', 'driver__user', 'vehicle')
        return Response(JourneySerializer(qs, many=True).data)
