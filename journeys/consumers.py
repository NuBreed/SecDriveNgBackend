"""Django Channels WebSocket consumers for real-time journey management.

Three channels per journey:

  ws/journeys/{id}/          — JourneyConsumer  (state changes + lifecycle events)
  ws/journeys/{id}/tracking/ — TrackingConsumer (GPS location stream)
  ws/notifications/          — NotificationConsumer (per-user system messages)

Authentication
--------------
JWT token passed as ?token=<access_token> query param (standard for mobile WS).
The middleware (JWTAuthMiddleware) authenticates the user and attaches it to
scope['user']. Unauthenticated connections are immediately closed.

Reconnection (Story 13)
-----------------------
Clients may buffer location updates offline and POST them via the REST endpoint
on reconnect; the dedup logic in services.record_location prevents duplicates.
"""
import json
import logging

from channels.generic.websocket import AsyncJsonWebsocketConsumer
from channels.db import database_sync_to_async

logger = logging.getLogger(__name__)


class JourneyConsumer(AsyncJsonWebsocketConsumer):
    """Journey state + event stream.

    Group name: ``journey_{id}``
    """

    async def connect(self):
        self.journey_id = str(self.scope['url_route']['kwargs']['journey_id'])
        self.group_name = f'journey_{self.journey_id}'
        self.user = self.scope.get('user')

        if self.user is None or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        # Verify the user is a participant in this journey before subscribing.
        if not await self._can_access():
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json({
            'type': 'connection.established',
            'journey_id': self.journey_id,
            'message': 'Connected to journey channel.',
        })
        # Log passenger/participant connect event.
        await self._log_connect()

    async def disconnect(self, code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            await self._log_disconnect()

    async def receive_json(self, content, **kwargs):
        """Handle inbound messages from the client."""
        msg_type = content.get('type', '')
        if msg_type == 'ping':
            await self.send_json({'type': 'pong'})

    # ── Group message handler ─────────────────────────────────────────────────

    async def journey_event(self, event):
        """Forward a group message to this WebSocket client."""
        await self.send_json(event)

    # ── DB helpers ────────────────────────────────────────────────────────────

    @database_sync_to_async
    def _can_access(self):
        from journeys.models import Journey
        try:
            j = Journey.objects.get(id=self.journey_id)
        except Journey.DoesNotExist:
            return False
        user = self.user
        return (
            j.passenger_id == user.pk
            or j.driver.user_id == user.pk
            or user.is_staff
        )

    @database_sync_to_async
    def _log_connect(self):
        from journeys.models import Journey, JourneyEvent
        try:
            j = Journey.objects.get(id=self.journey_id)
        except Journey.DoesNotExist:
            return
        user = self.user
        driver = getattr(j, 'driver', None)
        if driver and driver.user_id == user.pk:
            ev = JourneyEvent.EventType.PARTICIPANT_CONNECTED
        else:
            ev = JourneyEvent.EventType.PASSENGER_CONNECTED
        JourneyEvent.objects.create(journey=j, event_type=ev, actor=user)

    @database_sync_to_async
    def _log_disconnect(self):
        from journeys.models import Journey, JourneyEvent
        try:
            j = Journey.objects.get(id=self.journey_id)
        except Journey.DoesNotExist:
            return
        user = self.user
        driver = getattr(j, 'driver', None)
        if driver and driver.user_id == user.pk:
            ev = JourneyEvent.EventType.PARTICIPANT_DISCONNECTED
        else:
            ev = JourneyEvent.EventType.PASSENGER_DISCONNECTED
        JourneyEvent.objects.create(journey=j, event_type=ev, actor=user)


class TrackingConsumer(AsyncJsonWebsocketConsumer):
    """Real-time GPS location stream for a journey.

    Clients send location frames; the server fan-outs to the journey group.
    Group name: ``tracking_{id}``
    """

    async def connect(self):
        self.journey_id = str(self.scope['url_route']['kwargs']['journey_id'])
        self.journey_group = f'journey_{self.journey_id}'
        self.tracking_group = f'tracking_{self.journey_id}'
        self.user = self.scope.get('user')

        if self.user is None or not self.user.is_authenticated:
            await self.close(code=4001)
            return

        if not await self._can_access():
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(self.tracking_group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, 'tracking_group'):
            await self.channel_layer.group_discard(self.tracking_group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        """Accept a GPS frame, persist it, broadcast to the journey group."""
        lat = content.get('latitude')
        lng = content.get('longitude')
        if lat is None or lng is None:
            await self.send_json({'type': 'error', 'detail': 'latitude and longitude required'})
            return

        loc_data = await self._record(
            lat=lat, lng=lng,
            speed=content.get('speed'),
            heading=content.get('heading'),
            accuracy=content.get('accuracy'),
            altitude=content.get('altitude'),
            client_timestamp=content.get('client_timestamp'),
        )
        if loc_data is not None:
            await self.channel_layer.group_send(
                self.journey_group,
                {'type': 'journey.event', 'event': 'location.updated', **loc_data},
            )

    async def journey_event(self, event):
        await self.send_json(event)

    @database_sync_to_async
    def _can_access(self):
        from journeys.models import Journey
        try:
            j = Journey.objects.get(id=self.journey_id)
        except Journey.DoesNotExist:
            return False
        u = self.user
        return j.passenger_id == u.pk or j.driver.user_id == u.pk or u.is_staff

    @database_sync_to_async
    def _record(self, lat, lng, speed, heading, accuracy, altitude, client_timestamp):
        from journeys.models import Journey
        from journeys.services import record_location, JourneyError
        from django.utils.dateparse import parse_datetime
        try:
            j = Journey.objects.get(id=self.journey_id)
        except Journey.DoesNotExist:
            return None
        ts = parse_datetime(client_timestamp) if isinstance(client_timestamp, str) else None
        try:
            loc = record_location(j, lat, lng, speed=speed, heading=heading,
                                  accuracy=accuracy, altitude=altitude, client_timestamp=ts)
        except JourneyError:
            return None
        return {
            'journey_id': str(j.id),
            'status': j.status,
            'data': {'lat': loc.latitude, 'lng': loc.longitude,
                     'speed': loc.speed, 'heading': loc.heading},
        }


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """Per-user notification channel.

    Group name: ``notifications_{user_id}``
    """

    async def connect(self):
        self.user = self.scope.get('user')
        if self.user is None or not self.user.is_authenticated:
            await self.close(code=4001)
            return
        self.group_name = f'notifications_{self.user.pk}'
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if content.get('type') == 'ping':
            await self.send_json({'type': 'pong'})

    async def notification_message(self, event):
        await self.send_json(event)
