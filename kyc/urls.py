from django.urls import path

from kyc import views

app_name = 'kyc'

urlpatterns = [
    path('identity/', views.IdentitySubmitView.as_view(), name='identity'),
    path('selfie/', views.SelfieView.as_view(), name='selfie'),
    path('status/', views.KYCStatusView.as_view(), name='status'),
    path('admin/queue/', views.AdminQueueView.as_view(), name='admin-queue'),
]
