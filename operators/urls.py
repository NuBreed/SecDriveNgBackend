from django.urls import path

from operators import views

app_name = 'operators'

urlpatterns = [
    path('verification/', views.OperatorVerificationView.as_view(), name='verification'),
    path('verification/status/', views.OperatorVerificationStatusView.as_view(), name='verification-status'),
]
