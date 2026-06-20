from django.urls import path

from accident_detection import views

app_name = 'accident_detection'

# Journey-scoped patterns — mounted at /api/v1/journeys/<uuid:pk>/ in config/urls.py.
journey_urlpatterns = [
    path('sensor-data/', views.SensorDataView.as_view(), name='sensor-data'),
    path('sos/', views.SOSTriggerView.as_view(), name='sos'),
    path('panic/', views.PanicTriggerView.as_view(), name='panic'),
    path('accident-confirm/', views.AccidentConfirmView.as_view(), name='accident-confirm'),
    path('emergency/', views.EmergencyTimelineView.as_view(), name='emergency-timeline'),
    path('emergency/delivery/', views.DeliveryHealthView.as_view(), name='delivery-health'),
]

# Admin-scoped patterns.
admin_urlpatterns = [
    path('admin/emergencies/', views.AdminActiveEmergenciesView.as_view(), name='admin-emergencies'),
    path('admin/emergencies/logs/', views.AdminEscalationLogsView.as_view(), name='admin-logs'),
]
