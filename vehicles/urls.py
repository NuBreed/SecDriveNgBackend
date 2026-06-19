from django.urls import path

from vehicles import views

app_name = 'vehicles'

urlpatterns = [
    path('verification/', views.VehicleVerificationView.as_view(), name='verification'),
    path('verification/status/', views.VehicleVerificationStatusView.as_view(), name='verification-status'),
    path('<int:pk>/qr/', views.VehicleQRView.as_view(), name='qr'),
]
