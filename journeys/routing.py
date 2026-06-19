from django.urls import path

from journeys.consumers import JourneyConsumer, TrackingConsumer, NotificationConsumer

websocket_urlpatterns = [
    path('ws/journeys/<uuid:journey_id>/', JourneyConsumer.as_asgi()),
    path('ws/journeys/<uuid:journey_id>/tracking/', TrackingConsumer.as_asgi()),
    path('ws/notifications/', NotificationConsumer.as_asgi()),
]
