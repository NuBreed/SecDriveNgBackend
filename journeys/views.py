from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from journeys.models import Journey, JourneyEvent, JourneyLocation, JourneySensorData
from journeys.serializers import (
    JourneySerializer,
    DriverJourneySerializer,
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
            d = ser.validated_data
            journey = services.create_journey(
                passenger=request.user,
                participant_token=d['participant_token'],
                asset_token=d['asset_token'],
                group_size=d.get('group_size', 1),
                origin_lat=d.get('origin_lat'),
                origin_lng=d.get('origin_lng'),
                origin_address=d.get('origin_address', ''),
                destination_lat=d.get('destination_lat'),
                destination_lng=d.get('destination_lng'),
                destination_address=d.get('destination_address', ''),
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


class JourneyAcceptView(APIView):
    """POST /api/v1/journeys/{id}/accept/ — driver accepts an incoming ride request."""
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses=JourneySerializer, summary='Driver accepts a ride request')
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        try:
            journey = services.accept_journey(journey, request.user)
        except services.JourneyError as exc:
            return Response({'detail': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(JourneySerializer(journey).data)


class JourneyDeclineView(APIView):
    """POST /api/v1/journeys/{id}/decline/ — driver declines an incoming ride request."""
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses=JourneySerializer, summary='Driver declines a ride request')
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        try:
            journey = services.decline_journey(journey, request.user)
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
    """GET /POST /api/v1/journeys/{id}/locations/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=JourneyLocationSerializer(many=True),
        summary='List all GPS location pings for a journey (chronological)',
    )
    def get(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        locs = journey.locations.order_by('timestamp')
        return Response(JourneyLocationSerializer(locs, many=True).data)

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


class DriverPendingRequestsView(APIView):
    """GET /api/v1/journeys/driver/pending/ — CREATED journeys waiting for this driver."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=DriverJourneySerializer(many=True),
        summary='Pending ride requests for the authenticated driver',
    )
    def get(self, request):
        from drivers.models import Driver
        try:
            driver = Driver.objects.get(user=request.user)
        except Driver.DoesNotExist:
            return Response({'detail': 'Driver profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        qs = (
            Journey.objects
            .filter(driver=driver, status=Journey.Status.CREATED)
            .select_related('passenger')
            .order_by('created_at')
        )
        return Response(DriverJourneySerializer(qs, many=True).data)


class DriverTodayJourneysView(APIView):
    """GET /api/v1/journeys/driver/today/ — today's passenger list for the authenticated driver."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=DriverJourneySerializer(many=True),
        summary="Today's passengers for the authenticated driver",
    )
    def get(self, request):
        from django.utils import timezone
        from drivers.models import Driver
        try:
            driver = Driver.objects.get(user=request.user)
        except Driver.DoesNotExist:
            return Response({'detail': 'Driver profile not found.'}, status=status.HTTP_404_NOT_FOUND)
        today = timezone.localdate()
        qs = (
            Journey.objects
            .filter(driver=driver, created_at__date=today)
            .select_related('passenger')
            .prefetch_related('locations')
            .order_by('-created_at')
        )
        return Response(DriverJourneySerializer(qs, many=True).data)


# ── Admin views ────────────────────────────────────────────────────────────────

class JourneyPassengersView(APIView):
    """GET /api/v1/journeys/{id}/passengers/

    Returns all active passengers sharing the same driver as this journey.
    Accessible by either the passenger or the driver of the journey.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err

        # All live journeys for the same driver (includes the requester's own).
        live = Journey.objects.filter(
            driver=journey.driver,
            status__in=[
                Journey.Status.CREATED,
                Journey.Status.VERIFIED,
                Journey.Status.ACTIVE,
                Journey.Status.PAUSED,
            ],
        ).select_related('passenger')

        data = [
            {
                'journey_id':          str(j.id),
                'passenger_name':      (
                    f'{j.passenger.first_name} {j.passenger.last_name}'.strip()
                    or j.passenger.email
                ),
                'passenger_phone':     getattr(j.passenger, 'phone_number', '') or '',
                'origin_address':      j.origin_address or '',
                'destination_address': j.destination_address or '',
                'group_size':          j.group_size,
                'status':              j.status,
                'is_me':               j.passenger_id == request.user.pk,
            }
            for j in live
        ]
        return Response(data)


class AdminLiveJourneysView(APIView):
    """GET /api/v1/journeys/admin/live/ — all live journeys."""
    permission_classes = [IsAdminUser]

    @extend_schema(responses=JourneySerializer(many=True), summary='All live journeys (admin)')
    def get(self, request):
        qs = Journey.objects.filter(
            status__in=[Journey.Status.ACTIVE, Journey.Status.PAUSED, Journey.Status.INCIDENT],
        ).select_related('passenger', 'driver__user', 'vehicle')
        return Response(JourneySerializer(qs, many=True).data)


class JourneyPlannedRouteView(APIView):
    """GET /api/v1/journeys/{id}/planned-route/

    Returns a minimal two-point route (origin → destination) as waypoints.
    The Flutter deviation detector needs at least 2 points to work.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err

        waypoints = []
        if journey.origin_lat is not None and journey.origin_lng is not None:
            waypoints.append({'lat': journey.origin_lat, 'lng': journey.origin_lng})
        if journey.destination_lat is not None and journey.destination_lng is not None:
            waypoints.append({'lat': journey.destination_lat, 'lng': journey.destination_lng})

        return Response({'waypoints': waypoints})


class JourneySensorDataView(APIView):
    """GET /POST /api/v1/journeys/{id}/sensor-data/

    GET  — returns the last N sensor readings (default 20) for safety report.
    POST — records an accelerometer + GPS sample from the passenger app.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        limit = min(int(request.query_params.get('limit', 20)), 100)
        readings = journey.sensor_data.order_by('-timestamp')[:limit]
        return Response([
            {
                'acceleration_magnitude': r.acceleration_magnitude,
                'speed': r.speed,
                'lat': r.lat,
                'lng': r.lng,
                'timestamp': r.timestamp.isoformat(),
            }
            for r in readings
        ])

    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err

        # Passenger only — drivers don't post sensor data.
        if journey.passenger_id != request.user.pk:
            return Response(
                {'detail': 'Only the passenger can post sensor data.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        required = ('acceleration_x', 'acceleration_y', 'acceleration_z', 'acceleration_magnitude')
        missing = [f for f in required if f not in request.data]
        if missing:
            return Response(
                {'detail': f'Missing fields: {missing}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        JourneySensorData.objects.create(
            journey=journey,
            acceleration_x=float(request.data['acceleration_x']),
            acceleration_y=float(request.data['acceleration_y']),
            acceleration_z=float(request.data['acceleration_z']),
            acceleration_magnitude=float(request.data['acceleration_magnitude']),
            speed=float(request.data['speed']) if 'speed' in request.data else None,
            lat=float(request.data['lat']) if 'lat' in request.data else None,
            lng=float(request.data['lng']) if 'lng' in request.data else None,
        )
        return Response({'status': 'recorded'}, status=status.HTTP_201_CREATED)


class JourneyAccidentConfirmView(APIView):
    """POST /api/v1/journeys/{id}/accident-confirm/

    Records the passenger's response to a crash detection alert.
    Body: { "event_id": "<uuid>", "response": "SAFE" | "NEEDS_HELP" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err

        response_val = request.data.get('response', '')
        if response_val not in ('SAFE', 'NEEDS_HELP'):
            return Response(
                {'detail': 'response must be SAFE or NEEDS_HELP'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Log as a journey event so admins and sharing viewers can see it.
        JourneyEvent.objects.create(
            journey=journey,
            event_type=JourneyEvent.EventType.ALERT,
            actor=request.user,
            metadata={
                'type': 'accident_confirm',
                'response': response_val,
                'event_id': request.data.get('event_id', ''),
            },
        )

        return Response({'status': 'recorded', 'response': response_val})
