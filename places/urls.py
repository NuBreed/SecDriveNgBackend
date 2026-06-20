from django.urls import path
from places.views import PlaceAutocompleteView

app_name = 'places'

urlpatterns = [
    path('autocomplete/', PlaceAutocompleteView.as_view(), name='autocomplete'),
]
