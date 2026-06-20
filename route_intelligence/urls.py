from django.urls import path

from route_intelligence import views

app_name = 'route_intelligence'

# These are mounted as sub-paths of /api/v1/journeys/{pk}/ in config/urls.py.
# The journey-scoped patterns use a <uuid:pk> captured by the parent include.
journey_urlpatterns = [
    path('planned-route/', views.PlannedRouteView.as_view(), name='planned-route'),
    path('risk/', views.JourneyRiskView.as_view(), name='risk'),
    path('route-analysis/', views.RouteAnalysisView.as_view(), name='route-analysis'),
    path('warnings/', views.JourneyWarningsView.as_view(), name='warnings'),
    path('escalate/', views.JourneyEscalateView.as_view(), name='escalate'),
]

# Admin-scoped patterns.
admin_urlpatterns = [
    path('admin/risk/high-risk/', views.AdminHighRiskJourneysView.as_view(), name='high-risk'),
]
