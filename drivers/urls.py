from django.urls import path

from drivers import views

app_name = 'drivers'

urlpatterns = [
    path('verification/', views.DriverVerificationView.as_view(), name='verification'),
    path('verification/status/', views.DriverVerificationStatusView.as_view(), name='verification-status'),
    path('qr/', views.DriverQRView.as_view(), name='qr'),
]
