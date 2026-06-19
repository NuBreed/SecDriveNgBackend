from django.urls import path

from journeys import views

app_name = 'journeys'

urlpatterns = [
    # Collection + create
    path('', views.JourneyListCreateView.as_view(), name='list-create'),
    # Dashboard shortcuts (must come before <pk> patterns)
    path('history/', views.JourneyHistoryView.as_view(), name='history'),
    path('active/', views.ActiveJourneyView.as_view(), name='active'),
    path('admin/live/', views.AdminLiveJourneysView.as_view(), name='admin-live'),
    # Individual journey
    path('<uuid:pk>/', views.JourneyDetailView.as_view(), name='detail'),
    path('<uuid:pk>/destination/', views.JourneyDestinationView.as_view(), name='destination'),
    path('<uuid:pk>/start/', views.JourneyStartView.as_view(), name='start'),
    path('<uuid:pk>/pause/', views.JourneyPauseView.as_view(), name='pause'),
    path('<uuid:pk>/resume/', views.JourneyResumeView.as_view(), name='resume'),
    path('<uuid:pk>/complete/', views.JourneyCompleteView.as_view(), name='complete'),
    path('<uuid:pk>/cancel/', views.JourneyCancelView.as_view(), name='cancel'),
    path('<uuid:pk>/locations/', views.JourneyLocationView.as_view(), name='locations'),
    path('<uuid:pk>/timeline/', views.JourneyTimelineView.as_view(), name='timeline'),
]
