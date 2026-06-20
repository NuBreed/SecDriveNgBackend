"""Views for journey sharing, tracking links, and iSafePass subscription."""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema
from drf_spectacular.types import OpenApiTypes

from integrations.models import JourneySubscription
from journeys.models import Journey, JourneyShare, TrackingLink
from journeys import sharing as sharing_svc


def _get_journey(pk, user):
    try:
        j = Journey.objects.get(id=pk)
    except Journey.DoesNotExist:
        return None, Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
    if j.passenger_id != user.pk and not user.is_staff:
        return None, Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
    return j, None


# ── Sharing endpoints ─────────────────────────────────────────────────────────

class JourneyShareView(APIView):
    """POST /api/v1/journeys/{id}/share/ — share with selected contacts."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'contact_ids': {'type': 'array', 'items': {'type': 'string', 'format': 'uuid'}},
                    'privacy': {'type': 'object'},
                },
                'required': ['contact_ids'],
            }
        },
        responses={200: OpenApiTypes.OBJECT},
        summary='Share journey with selected trusted contacts',
    )
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        contact_ids = request.data.get('contact_ids', [])
        if not contact_ids:
            return Response({'detail': 'contact_ids is required.'}, status=status.HTTP_400_BAD_REQUEST)
        privacy = request.data.get('privacy', {})
        shares = sharing_svc.share_journey(journey, contact_ids, privacy)
        # Notify newly added recipients.
        sharing_svc.notify_recipients(journey, 'journey.shared', {
            'message': 'A journey has been shared with you.',
        })
        return Response({
            'shared_with': len(shares),
            'journey_id': str(journey.id),
        })


class JourneySharedStatusView(APIView):
    """GET /api/v1/journeys/{id}/shared/ — who is currently monitoring."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT},
                   summary='View current sharing recipients for this journey')
    def get(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        shares = JourneyShare.objects.filter(
            journey=journey, active=True,
        ).select_related('contact')
        return Response({
            'journey_id': str(journey.id),
            'recipients': [
                {
                    'contact_id': str(s.contact_id),
                    'name': s.contact.name,
                    'type': s.contact.contact_type,
                    'privacy': s.get_privacy(),
                    'shared_at': s.shared_at,
                }
                for s in shares
            ],
        })


class JourneyUnshareView(APIView):
    """POST /api/v1/journeys/{id}/unshare/ — stop sharing."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'contact_ids': {
                        'type': 'array', 'items': {'type': 'string', 'format': 'uuid'},
                        'description': 'Leave empty to unshare with everyone.',
                    },
                },
            }
        },
        responses={200: OpenApiTypes.OBJECT},
        summary='Remove sharing recipients (or all)',
    )
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        contact_ids = request.data.get('contact_ids') or None
        count = sharing_svc.unshare_journey(journey, contact_ids)
        return Response({'unshared_from': count, 'journey_id': str(journey.id)})


# ── Tracking link endpoints ────────────────────────────────────────────────────

class TrackingLinkCreateView(APIView):
    """POST /api/v1/journeys/{id}/tracking-link/ — generate a shareable link."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=None,
        responses={201: OpenApiTypes.OBJECT},
        summary='Generate a secure tracking link for this journey',
    )
    def post(self, request, pk):
        journey, err = _get_journey(pk, request.user)
        if err:
            return err
        hours = int(request.data.get('expires_hours', 24))
        link = sharing_svc.generate_tracking_link(journey, request.user, expires_hours=hours)
        return Response({
            'token': link.token,
            'tracking_url': sharing_svc.tracking_url(link.token),
            'expires_at': link.expires_at,
        }, status=status.HTTP_201_CREATED)


class PublicTrackingView(APIView):
    """GET /api/v1/tracking/{token}/ — unauthenticated live journey status."""
    permission_classes = [AllowAny]

    @extend_schema(
        responses={200: OpenApiTypes.OBJECT},
        summary='View live journey status via a tracking link (no auth required)',
    )
    def get(self, request, token):
        link = sharing_svc.resolve_tracking_link(token)
        if link is None:
            return Response({'detail': 'Invalid or expired tracking link.'},
                            status=status.HTTP_404_NOT_FOUND)
        journey = link.journey
        loc = journey.last_location
        return Response({
            'journey_id': str(journey.id),
            'status': journey.status,
            'passenger_name': (
                f'{journey.passenger.first_name} {journey.passenger.last_name}'.strip()
                or journey.passenger.username
            ),
            'origin_address': journey.origin_address,
            'destination_address': journey.destination_address,
            'estimated_duration_s': journey.estimated_duration_s,
            'estimated_distance_m': journey.estimated_distance_m,
            'started_at': journey.started_at,
            'current_location': {
                'lat': loc.latitude, 'lng': loc.longitude,
                'speed': loc.speed, 'heading': loc.heading,
                'timestamp': loc.timestamp,
            } if loc else None,
        })


# ── iSafePass manual trigger endpoints ────────────────────────────────────────

class ISafePassSubscribeView(APIView):
    """POST /api/v1/isafepass/subscribe/ — manually trigger a subscription."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request={'application/json': {'type': 'object',
                                      'properties': {'journey_id': {'type': 'string', 'format': 'uuid'}},
                                      'required': ['journey_id']}},
        responses={200: OpenApiTypes.OBJECT},
        summary='Manually subscribe a journey to iSafePass monitoring',
    )
    def post(self, request):
        journey_id = request.data.get('journey_id')
        try:
            journey = Journey.objects.get(id=journey_id, passenger=request.user)
        except Journey.DoesNotExist:
            return Response({'detail': 'Journey not found.'}, status=status.HTTP_404_NOT_FOUND)
        sub = sharing_svc._subscribe_isafepass(journey)
        return Response({
            'status': sub.status,
            'isafepass_subscription_id': sub.isafepass_subscription_id,
        })


class ISafePassUnsubscribeView(APIView):
    """POST /api/v1/isafepass/unsubscribe/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request={'application/json': {'type': 'object',
                                      'properties': {'journey_id': {'type': 'string', 'format': 'uuid'}},
                                      'required': ['journey_id']}},
        responses={200: OpenApiTypes.OBJECT},
        summary='Manually close the iSafePass subscription for a journey',
    )
    def post(self, request):
        journey_id = request.data.get('journey_id')
        try:
            journey = Journey.objects.get(id=journey_id, passenger=request.user)
        except Journey.DoesNotExist:
            return Response({'detail': 'Journey not found.'}, status=status.HTTP_404_NOT_FOUND)
        sharing_svc.unsubscribe_isafepass(journey)
        return Response({'detail': 'Unsubscribed.'})
