from django.urls import path

from accounts import views

app_name = 'accounts'

urlpatterns = [
    path('register/', views.RegisterAPIView.as_view(), name='register'),
    path('verify-otp/', views.VerifyOTPAPIView.as_view(), name='verify-otp'),
    path('resend-otp/', views.ResendOTPAPIView.as_view(), name='resend-otp'),
    path('login/', views.LoginAPIView.as_view(), name='login'),
    path('logout/', views.LogoutAPIView.as_view(), name='logout'),
    path('refresh/', views.SecDriveTokenRefreshView.as_view(), name='refresh'),
    path('forgot-password/', views.ForgotPasswordAPIView.as_view(), name='forgot-password'),
    path('reset-password/', views.ResetPasswordAPIView.as_view(), name='reset-password'),
    path('change-password/', views.ChangePasswordAPIView.as_view(), name='change-password'),

    # Google
    path('google/', views.GoogleAuthAPIView.as_view(), name='google'),

    # iSafePass SSO (bridge)
    path('isafepass/login/', views.ISafePassLoginAPIView.as_view(), name='isafepass-login'),
    path('isafepass/callback/', views.ISafePassCallbackAPIView.as_view(), name='isafepass-callback'),
    path('isafepass/link/', views.ISafePassLinkAPIView.as_view(), name='isafepass-link'),

    # Dashboard / account management
    path('me/', views.MeAPIView.as_view(), name='me'),
    path('devices/', views.DevicesAPIView.as_view(), name='devices'),
    path('sessions/', views.SessionsAPIView.as_view(), name='sessions'),
    path('login-history/', views.LoginHistoryAPIView.as_view(), name='login-history'),
]
