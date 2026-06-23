from django.urls import path

from journeys import views
from journeys import sharing_views

app_name = 'journeys'

urlpatterns = [
    # Collection + create
    path('', views.JourneyListCreateView.as_view(), name='list-create'),
    # Dashboard shortcuts (must come before <pk> patterns)
    path('history/', views.JourneyHistoryView.as_view(), name='history'),
    path('active/', views.ActiveJourneyView.as_view(), name='active'),
    path('admin/live/', views.AdminLiveJourneysView.as_view(), name='admin-live'),
    path('driver/pending/', views.DriverPendingRequestsView.as_view(), name='driver-pending'),
    path('driver/today/', views.DriverTodayJourneysView.as_view(), name='driver-today'),
    # Individual journey
    path('<uuid:pk>/', views.JourneyDetailView.as_view(), name='detail'),
    path('<uuid:pk>/destination/', views.JourneyDestinationView.as_view(), name='destination'),
    path('<uuid:pk>/accept/', views.JourneyAcceptView.as_view(), name='accept'),
    path('<uuid:pk>/decline/', views.JourneyDeclineView.as_view(), name='decline'),
    path('<uuid:pk>/start/', views.JourneyStartView.as_view(), name='start'),
    path('<uuid:pk>/pause/', views.JourneyPauseView.as_view(), name='pause'),
    path('<uuid:pk>/resume/', views.JourneyResumeView.as_view(), name='resume'),
    path('<uuid:pk>/complete/', views.JourneyCompleteView.as_view(), name='complete'),
    path('<uuid:pk>/cancel/', views.JourneyCancelView.as_view(), name='cancel'),
    path('<uuid:pk>/locations/', views.JourneyLocationView.as_view(), name='locations'),
    path('<uuid:pk>/passengers/', views.JourneyPassengersView.as_view(), name='passengers'),
    path('<uuid:pk>/planned-route/', views.JourneyPlannedRouteView.as_view(), name='planned-route'),
    path('<uuid:pk>/sensor-data/', views.JourneySensorDataView.as_view(), name='sensor-data'),
    path('<uuid:pk>/accident-confirm/', views.JourneyAccidentConfirmView.as_view(), name='accident-confirm'),
    path('<uuid:pk>/timeline/', views.JourneyTimelineView.as_view(), name='timeline'),
    # Sharing
    path('<uuid:pk>/share/', sharing_views.JourneyShareView.as_view(), name='share'),
    path('<uuid:pk>/shared/', sharing_views.JourneySharedStatusView.as_view(), name='shared'),
    path('<uuid:pk>/unshare/', sharing_views.JourneyUnshareView.as_view(), name='unshare'),
    path('<uuid:pk>/tracking-link/', sharing_views.TrackingLinkCreateView.as_view(), name='tracking-link'),
]
