from django.urls import path

from qr_codes import views

app_name = 'qr'

urlpatterns = [
    # Generation
    path('participants/generate/', views.ParticipantQRGenerateView.as_view(), name='participant-generate'),
    path('assets/generate/', views.AssetQRGenerateView.as_view(), name='asset-generate'),
    # Verification
    path('verify/', views.QRVerifyView.as_view(), name='verify'),
    # Individual QR record
    path('<uuid:pk>/', views.QRDetailView.as_view(), name='detail'),
    path('<uuid:pk>/revoke/', views.QRRevokeView.as_view(), name='revoke'),
    path('<uuid:pk>/regenerate/', views.QRRegenerateView.as_view(), name='regenerate'),
    # Scan history (admin)
    path('scans/', views.QRScanListView.as_view(), name='scan-list'),
    path('scans/<uuid:pk>/', views.QRScanDetailView.as_view(), name='scan-detail'),
]
