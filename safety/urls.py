from django.urls import path

from safety import views

app_name = 'safety'

urlpatterns = [
    path('', views.TrustedContactListCreateView.as_view(), name='list-create'),
    path('<uuid:pk>/', views.TrustedContactDetailView.as_view(), name='detail'),
]
