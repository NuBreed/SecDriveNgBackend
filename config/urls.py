from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include

from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
)

from common.views import DocumentDownloadView
from route_intelligence.urls import journey_urlpatterns as ri_journey_urls, admin_urlpatterns as ri_admin_urls, safety_urlpatterns as ri_safety_urls
from accident_detection.urls import journey_urlpatterns as ad_journey_urls, admin_urlpatterns as ad_admin_urls

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
    # Route intelligence endpoints nested under /journeys/{pk}/
    path('api/v1/journeys/<uuid:pk>/', include(ri_journey_urls)),
    path('api/v1/', include(ri_admin_urls)),
    # Accident detection endpoints nested under /journeys/{pk}/
    path('api/v1/journeys/<uuid:pk>/', include(ad_journey_urls)),
    path('api/v1/', include(ad_admin_urls)),
    path('api/v1/contacts/', include('safety.urls')),
    path('api/v1/places/', include('places.urls')),
    path('api/v1/safety/', include(ri_safety_urls)),
    path('api/v1/tracking/', include('journeys.tracking_urls')),
    path('api/v1/isafepass/', include('integrations.urls')),
    # API schema + docs
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
