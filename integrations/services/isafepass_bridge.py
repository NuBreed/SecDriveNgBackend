"""
Trusted backend bridge to the iSafePass platform (Stories 5 & 6).

iSafePass does not expose an OAuth2 server, but it is the same owner's system
and shares the database. Rather than a full OAuth client flow, SecDrive calls
iSafePass server-to-server with a shared service secret to (a) verify a user's
identity and (b) pull their emergency contacts / safety profile / trust network.

Until ``ISAFEPASS_BASE_URL`` and ``ISAFEPASS_SERVICE_SECRET`` are configured the
bridge is disabled and ``ISafePassUnavailable`` is raised, so the SSO endpoints
return a clean 503 rather than crashing. The actual iSafePass-side endpoint is a
separate cross-repo task; the request/response shape below is the contract.
"""
import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class ISafePassUnavailable(Exception):
    """Raised when the bridge is not configured or iSafePass is unreachable."""


class ISafePassBridge:
    def __init__(self):
        self.base_url = (settings.ISAFEPASS_BASE_URL or '').rstrip('/')
        self.secret = settings.ISAFEPASS_SERVICE_SECRET or ''
        self.timeout = getattr(settings, 'ISAFEPASS_TIMEOUT_SECONDS', 10)

    @property
    def enabled(self):
        return bool(self.base_url and self.secret)

    def _post(self, path, payload):
        if not self.enabled:
            raise ISafePassUnavailable('iSafePass integration is not configured.')

        import requests

        try:
            resp = requests.post(
                f'{self.base_url}{path}',
                json=payload,
                headers={'X-Service-Secret': self.secret},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except ISafePassUnavailable:
            raise
        except Exception as exc:
            logger.exception('iSafePass bridge call failed: %s', exc)
            raise ISafePassUnavailable('Could not reach iSafePass.') from exc

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
        return self._post('/api/bridge/verify/', {'credential': credential})

    def link_account(self, user, credential):
        """Confirm ownership of an iSafePass account for an existing SecDrive
        user, returning the same identity payload as ``verify_and_fetch``."""
        return self._post(
            '/api/bridge/link/',
            {'credential': credential, 'email': user.email, 'phone': user.phone},
        )


def get_bridge():
    return ISafePassBridge()
