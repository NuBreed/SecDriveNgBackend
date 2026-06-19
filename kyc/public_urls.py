from django.urls import path

from kyc.public_views import PublicVerifyView

urlpatterns = [
    path('verify/<str:token>/', PublicVerifyView.as_view(), name='public-verify'),
]
