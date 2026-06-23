from django.urls import path

from safety import views

app_name = 'safety'

urlpatterns = [
    path('',           views.TrustedContactListCreateView.as_view(), name='list-create'),
    path('<uuid:pk>/', views.TrustedContactDetailView.as_view(),     name='detail'),
    # ── New endpoints ──────────────────────────────────────────────────────────
    path('check/',    views.ContactCheckView.as_view(),              name='check'),
    path('trusted/',  views.AddTrustedContactView.as_view(),         name='add-trusted'),
    path('invite/',           views.ContactInviteView.as_view(),        name='invite'),
    path('isafepass-family/',  views.ISafePassFamilyView.as_view(),      name='isafepass-family'),
    path('location-safety/',   views.LocationSafetyCheckView.as_view(),  name='location-safety'),
]
