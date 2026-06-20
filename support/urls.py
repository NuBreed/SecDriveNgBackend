from django.urls import path
from .views import HelpArticleListView

urlpatterns = [
    path('', HelpArticleListView.as_view(), name='help-articles'),
]
