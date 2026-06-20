from django.urls import path

from operators import views

app_name = 'operators'

urlpatterns = [
    # KYC / verification
    path('verification/', views.OperatorVerificationView.as_view(), name='verification'),
    path('verification/status/', views.OperatorVerificationStatusView.as_view(), name='verification-status'),

    # Operator CRUD (Stories 1-2)
    path('', views.OperatorListCreateView.as_view(), name='operator-list'),
    path('<uuid:pk>/', views.OperatorDetailView.as_view(), name='operator-detail'),

    # Participants (Story 3)
    path('<uuid:pk>/participants/', views.ParticipantListView.as_view(), name='participant-list'),
    path('<uuid:pk>/participants/<uuid:pid>/', views.ParticipantDetailView.as_view(), name='participant-detail'),

    # Assets (Stories 4-5)
    path('<uuid:pk>/assets/', views.AssetListView.as_view(), name='asset-list'),
    path('<uuid:pk>/assets/<uuid:aid>/', views.AssetDetailView.as_view(), name='asset-detail'),
    path('<uuid:pk>/assets/<uuid:aid>/assign/', views.AssetAssignView.as_view(), name='asset-assign'),

    # Fleet dashboard, analytics, safety score (Stories 6-11, 14)
    path('<uuid:pk>/fleet/', views.FleetDashboardView.as_view(), name='fleet-dashboard'),
    path('<uuid:pk>/analytics/', views.FleetAnalyticsView.as_view(), name='fleet-analytics'),
    path('<uuid:pk>/safety-score/', views.FleetSafetyScoreView.as_view(), name='fleet-safety-score'),

    # Branches (Story 12)
    path('<uuid:pk>/branches/', views.BranchListView.as_view(), name='branch-list'),

    # Members / roles (Story 13)
    path('<uuid:pk>/members/', views.MemberListView.as_view(), name='member-list'),

    # Admin
    path('admin/', views.AdminOperatorListView.as_view(), name='admin-operators'),
]
