"""Route Intelligence API views."""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema
from drf_spectacular.types import OpenApiTypes

from journeys.models import Journey
from route_intelligence import services as ri_svc
from route_intelligence.models import (
    JourneyRisk, JourneyWarning, PlannedRoute, RouteDeviation, UnexpectedStop,
)
from route_intelligence.serializers import (
    EscalateSerializer, JourneyRiskSerializer, JourneyWarningSerializer,
    PlannedRouteSerializer, RouteAnalysisSerializer,
)


def _get_journey(pk, user):
    try:
        j = Journey.objects.get(id=pk)
    except Journey.DoesNotExist:
        return None, Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
    if j.passenger_id != user.pk and not user.is_staff:
        return None, Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
    return j, None


# ── Story 1: set / update planned route ───────────────────────────────────────

class PlannedRouteView(APIView):
    """GET / POST /api/v1/journeys/{id}/planned-route/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=PlannedRouteSerializer, summary='Get the planned route for a journey')
    def get(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        try:
            route = journey.planned_route
        except PlannedRoute.DoesNotExist:
            return Response({'detail': 'No planned route set.'}, status=status.HTTP_404_NOT_FOUND)
        return Response(PlannedRouteSerializer(route).data)

    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'waypoints': {'type': 'array',
                                  'items': {'type': 'object',
                                            'properties': {'lat': {'type': 'number'},
                                                           'lng': {'type': 'number'}}}},
                    'expected_duration_s': {'type': 'integer'},
                    'expected_distance_m': {'type': 'number'},
                },
                'required': ['waypoints'],
            }
        },
        responses={201: PlannedRouteSerializer},
        summary='Set or replace the planned route for a journey',
    )
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        waypoints = request.data.get('waypoints', [])
        if not isinstance(waypoints, list) or len(waypoints) < 2:
            return Response(
                {'detail': 'waypoints must be a list of at least 2 {lat, lng} points.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ri_svc.set_planned_route(
            journey, waypoints,
            expected_duration_s=request.data.get('expected_duration_s'),
            expected_distance_m=request.data.get('expected_distance_m'),
        )
        return Response(PlannedRouteSerializer(journey.planned_route).data,
                        status=status.HTTP_201_CREATED)


# ── Story 8: journey risk ─────────────────────────────────────────────────────

class JourneyRiskView(APIView):
    """GET /api/v1/journeys/{id}/risk/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=JourneyRiskSerializer, summary='Get the current risk score for a journey')
    def get(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        risk, _ = JourneyRisk.objects.get_or_create(journey=journey)
        return Response(JourneyRiskSerializer(risk).data)


# ── Story 2: route analysis dashboard ────────────────────────────────────────

class RouteAnalysisView(APIView):
    """GET /api/v1/journeys/{id}/route-analysis/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=RouteAnalysisSerializer, summary='Full route analysis for a journey')
    def get(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err

        try:
            planned_route = journey.planned_route
        except PlannedRoute.DoesNotExist:
            planned_route = None

        try:
            risk = journey.risk
        except JourneyRisk.DoesNotExist:
            risk = None

        show_resolved = request.query_params.get('show_resolved', '').lower() in ('1', 'true')
        dev_qs = RouteDeviation.objects.filter(journey=journey)
        stop_qs = UnexpectedStop.objects.filter(journey=journey)
        warn_qs = JourneyWarning.objects.filter(journey=journey)
        if not show_resolved:
            dev_qs = dev_qs.filter(is_resolved=False)
            stop_qs = stop_qs.filter(is_resolved=False)
            warn_qs = warn_qs.filter(is_resolved=False)

        data = {
            'journey_id': journey.id,
            'planned_route': planned_route,
            'deviations': list(dev_qs),
            'unexpected_stops': list(stop_qs),
            'risk': risk,
            'warnings': list(warn_qs),
        }
        return Response(RouteAnalysisSerializer(data).data)


# ── Story 9: warnings ─────────────────────────────────────────────────────────

class JourneyWarningsView(APIView):
    """GET /api/v1/journeys/{id}/warnings/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=JourneyWarningSerializer(many=True),
        summary='List safety warnings for a journey',
    )
    def get(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        qs = JourneyWarning.objects.filter(journey=journey)
        if request.query_params.get('active_only', '').lower() in ('1', 'true'):
            qs = qs.filter(is_resolved=False)
        return Response(JourneyWarningSerializer(qs, many=True).data)


# ── Story 11-12: escalate ─────────────────────────────────────────────────────

class JourneyEscalateView(APIView):
    """POST /api/v1/journeys/{id}/escalate/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=EscalateSerializer,
        responses={200: OpenApiTypes.OBJECT},
        summary='Manually escalate a journey to iSafePass as a safety incident',
    )
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        ser = EscalateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        result = ri_svc.escalate_to_isafepass(
            journey, reason=ser.validated_data.get('reason', ''),
        )
        if result is None:
            return Response(
                {'detail': 'Escalation recorded. iSafePass is not configured on this server.'},
                status=status.HTTP_200_OK,
            )
        return Response({
            'detail': 'Incident created in iSafePass.',
            'incident_id': result.get('incident_id', ''),
            'data': result,
        })


# ── Admin: high-risk journey list ─────────────────────────────────────────────

class AdminHighRiskJourneysView(APIView):
    """GET /api/v1/admin/risk/high-risk/ — admin dashboard (Story Admin)."""
    permission_classes = [IsAdminUser]

    @extend_schema(
        responses=JourneyRiskSerializer(many=True),
        summary='List journeys with HIGH or CRITICAL risk (admin)',
    )
    def get(self, request):
        qs = JourneyRisk.objects.filter(
            level__in=['HIGH', 'CRITICAL'],
        ).select_related('journey').order_by('-score')
        return Response(JourneyRiskSerializer(qs, many=True).data)
