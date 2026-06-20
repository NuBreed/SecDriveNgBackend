from django.urls import path

from journeys.sharing_views import PublicTrackingView

urlpatterns = [
    path('<str:token>/', PublicTrackingView.as_view(), name='tracking-public'),
]
