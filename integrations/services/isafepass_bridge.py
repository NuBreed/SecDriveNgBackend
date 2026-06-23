"""
Trusted backend bridge to the iSafePass platform (Stories 5 & 6).

SecDrive is registered as a DeveloperApplication on iSafePass with
bridge_enabled=True. All bridge calls authenticate with the developer
ecosystem's ApiKey mechanism:

    Authorization: Api-Key <ISAFEPASS_API_KEY_ID>:<ISAFEPASS_API_SECRET>

Until the three env vars are set the bridge is disabled and
``ISafePassUnavailable`` is raised, so SSO endpoints return 503 cleanly.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class ISafePassUnavailable(Exception):
    """Raised when the bridge is not configured or iSafePass is unreachable."""


class ISafePassBridge:
    def __init__(self):
        self.base_url  = (settings.ISAFEPASS_BASE_URL or '').rstrip('/')
        self.api_key_id = getattr(settings, 'ISAFEPASS_API_KEY_ID', '') or ''
        self.api_secret = getattr(settings, 'ISAFEPASS_API_SECRET', '') or ''
        self.timeout   = getattr(settings, 'ISAFEPASS_TIMEOUT_SECONDS', 10)
        self.origin    = self._detect_origin()

    def _detect_origin(self) -> str:
        """Derive this server's origin from ALLOWED_HOSTS.

        Picks the first non-wildcard, non-localhost host and wraps it with
        https:// so iSafePass can validate it against allowed_origins.
        Falls back to the raw first entry if nothing better is found.
        """
        hosts = getattr(settings, 'ALLOWED_HOSTS', [])
        skip = {'localhost', '127.0.0.1', '*'}
        import re
        _ip_re = re.compile(r'^\d{1,3}(\.\d{1,3}){3}$')
        for host in hosts:
            if host not in skip and not host.startswith('.'):
                scheme = 'http' if _ip_re.match(host) else 'https'
                return f'{scheme}://{host}'
        # last resort: first entry
        if hosts:
            return f'https://{hosts[0]}'
        return ''

    @property
    def enabled(self):
        return bool(self.base_url and self.api_key_id and self.api_secret)

    def _get(self, path, params=None):
        if not self.enabled:
            raise ISafePassUnavailable('iSafePass integration is not configured.')

        import requests

        try:
            resp = requests.get(
                f'{self.base_url}{path}',
                params=params,
                headers={
                    'Authorization': f'Api-Key {self.api_key_id}:{self.api_secret}',
                    'Origin': self.origin,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except ISafePassUnavailable:
            raise
        except Exception as exc:
            logger.exception('iSafePass bridge GET failed: %s', exc)
            raise ISafePassUnavailable('Could not reach iSafePass.') from exc

    def _post(self, path, payload):
        if not self.enabled:
            raise ISafePassUnavailable('iSafePass integration is not configured.')

        import requests

        try:
            resp = requests.post(
                f'{self.base_url}{path}',
                json=payload,
                headers={
                    'Authorization': f'Api-Key {self.api_key_id}:{self.api_secret}',
                    'Origin': self.origin,
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except ISafePassUnavailable:
            raise
        except Exception as exc:
            logger.exception('iSafePass bridge call failed: %s', exc)
            raise ISafePassUnavailable('Could not reach iSafePass.') from exc

    def get_token(self, email: str, password: str) -> str:
        """Exchange iSafePass email+password for an iSafePass access token.

        Uses the dedicated bridge endpoint (Api-Key authenticated) so this call
        is completely separate from the partner dashboard login flow.
        Returns the access token string.
        """
        data = self._post('/api/v1/bridge/user-token/', {'email': email, 'password': password})
        access = data.get('access')
        if not access:
            raise ISafePassUnavailable('iSafePass did not return an access token.')
        return access

    def verify_and_fetch(self, credential):
        """Verify an iSafePass credential (token/code) and return the user's
        identity plus safety data.

        Expected response shape:
            {
              "isafepass_user_id": "...",
              "email": "...",
              "phone": "...",
              "first_name": "...",
              "last_name": "...",
              "emergency_contacts": [...],
              "safety_profile": {...},
              "trust_network": [...]
            }
        """
        return self._post('/api/v1/bridge/verify/', {'credential': credential})

    def link_account(self, user, credential):
        """Confirm ownership of an iSafePass account for an existing SecDrive
        user, returning the same identity payload as ``verify_and_fetch``."""
        return self._post(
            '/api/v1/bridge/link/',
            {'credential': credential, 'email': user.email, 'phone': user.phone},
        )


    def subscribe_journey(self, journey) -> dict:
        """Notify iSafePass that a journey has started; returns subscription data.

        Expected response: {"subscription_id": "...", "monitoring_active": true, ...}
        """
        driver = journey.driver
        vehicle = journey.vehicle
        payload = {
            'journey_id': str(journey.id),
            'passenger_id': str(journey.passenger.uuid),
            'participant_id': str(driver.user.uuid),
            'asset_id': str(vehicle.pk),
            'origin': {
                'lat': journey.origin_lat,
                'lng': journey.origin_lng,
                'address': journey.origin_address,
            },
            'destination': {
                'lat': journey.destination_lat,
                'lng': journey.destination_lng,
                'address': journey.destination_address,
            },
        }
        return self._post('/api/v1/bridge/journey/subscribe/', payload)

    def unsubscribe_journey(self, subscription_id: str, reason: str = '') -> dict:
        """Close a journey monitoring subscription on iSafePass."""
        return self._post(
            '/api/v1/bridge/journey/unsubscribe/',
            {'subscription_id': subscription_id, 'reason': reason},
        )

    def trigger_sos(self, payload: dict) -> dict:
        """Trigger an SOS alert on iSafePass.

        Expected response: {"sos_id": "...", "status": "TRIGGERED", ...}
        """
        return self._post('/api/v1/bridge/sos/', payload)

    def create_incident(self, payload: dict) -> dict:
        """Create a safety incident in iSafePass for a journey that has crossed a risk threshold.

        Expected response: {"incident_id": "...", "status": "OPEN", ...}
        """
        return self._post('/api/v1/bridge/incidents/', payload)

    def get_location_safety(self, lat: float, lng: float, radius_m: int = 500) -> dict:
        """Query iSafePass for the safety rating of a GPS coordinate.

        Expected response:
            {
              "rating": "safe" | "moderate" | "unsafe",
              "score": 0-100,          # higher = safer
              "label": "Residential area — low incident history",
              "incident_count": 3,     # incidents within radius in last 30 days
              "categories": ["robbery", "assault"],   # dominant incident types
              "last_incident_at": "2024-05-01T13:22:00Z" | null
            }
        """
        return self._get(
            '/api/v1/safety/location/',
            params={'lat': lat, 'lng': lng, 'radius_m': radius_m},
        )


def get_bridge():
    return ISafePassBridge()
