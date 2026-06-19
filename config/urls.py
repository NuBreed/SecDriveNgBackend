from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)

from common.views import DocumentDownloadView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/v1/auth/', include('accounts.urls')),
    path('api/v1/kyc/', include('kyc.urls')),
    path('api/v1/drivers/', include('drivers.urls')),
    path('api/v1/vehicles/', include('vehicles.urls')),
    path('api/v1/operators/', include('operators.urls')),
    path('api/v1/documents/<uuid:pk>/file/', DocumentDownloadView.as_view(), name='document-download'),
    path('api/v1/', include('kyc.public_urls')),
    path('api/v1/qr/', include('qr_codes.urls')),
    path('api/v1/journeys/', include('journeys.urls')),
    # API schema + docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
