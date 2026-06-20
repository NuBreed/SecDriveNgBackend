from django.urls import path

from journeys.sharing_views import ISafePassSubscribeView, ISafePassUnsubscribeView

app_name = 'integrations'

urlpatterns = [
    path('subscribe/', ISafePassSubscribeView.as_view(), name='isafepass-subscribe'),
    path('unsubscribe/', ISafePassUnsubscribeView.as_view(), name='isafepass-unsubscribe'),
]
