"""Google Places API proxy — keeps the API key server-side."""
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_AUTOCOMPLETE_URL = 'https://maps.googleapis.com/maps/api/place/autocomplete/json'
_DETAILS_URL      = 'https://maps.googleapis.com/maps/api/place/details/json'


def autocomplete(query: str, session_token: str = '') -> list[dict]:
    """
    Return a list of place suggestions for *query*.
    Each item has: place_id, description, structured_formatting.
    """
    key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '')
    if not key:
        logger.warning('GOOGLE_MAPS_API_KEY not configured — autocomplete unavailable.')
        return []

    params = {
        'input':       query,
        'key':         key,
        'language':    'en',
        'components':  'country:ng',   # bias to Nigeria; remove if global
    }
    if session_token:
        params['sessiontoken'] = session_token

    try:
        resp = requests.get(_AUTOCOMPLETE_URL, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') not in ('OK', 'ZERO_RESULTS'):
            logger.error('Places autocomplete error: %s', data.get('status'))
            return []
        return data.get('predictions', [])
    except Exception as exc:
        logger.exception('Places autocomplete request failed: %s', exc)
        return []


def place_details(place_id: str, session_token: str = '') -> dict | None:
    """Return lat/lng and formatted_address for a place_id."""
    key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '')
    if not key:
        return None

    params = {
        'place_id': place_id,
        'fields':   'place_id,name,formatted_address,geometry',
        'key':      key,
        'language': 'en',
    }
    if session_token:
        params['sessiontoken'] = session_token

    try:
        resp = requests.get(_DETAILS_URL, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if data.get('status') != 'OK':
            return None
        return data.get('result')
    except Exception as exc:
        logger.exception('Places details request failed: %s', exc)
        return None
