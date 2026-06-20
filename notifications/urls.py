from django.urls import path
from .views import NotificationListView, NotificationMarkReadView, NotificationPrefsView

urlpatterns = [
    path('',       NotificationListView.as_view(),   name='notification-list'),
    path('read/',  NotificationMarkReadView.as_view(), name='notification-mark-read'),
    path('prefs/', NotificationPrefsView.as_view(),   name='notification-prefs'),
]
