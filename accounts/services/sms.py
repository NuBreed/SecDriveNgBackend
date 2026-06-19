"""
SMS delivery.
"""
import abc
import logging

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class SMSResult:
    def __init__(self, success, detail='', expose_code=False):
        self.success = success
        self.detail = detail
        # When True, callers may return the OTP code in the API response
        # (dev/testing only — never with a real provider).
        self.expose_code = expose_code


class SMSBackend(abc.ABC):
    @abc.abstractmethod
    def send(self, to, message):
        """Send ``message`` to phone number ``to``. Returns an SMSResult."""
        raise NotImplementedError


class ConsoleSMSBackend(SMSBackend):
    """Logs the SMS instead of sending it; exposes the code for testing."""

    def send(self, to, message):
        logger.info('[ConsoleSMS] to=%s message=%s', to, message)
        return SMSResult(success=True, detail='logged to console', expose_code=True)


class AfricasTalkingSMSBackend(SMSBackend):
    """Sends SMS via the Africa's Talking REST API (no SDK dependency)."""

    ENDPOINT = 'https://api.africastalking.com/version1/messaging'
    SANDBOX_ENDPOINT = 'https://api.sandbox.africastalking.com/version1/messaging'

    def send(self, to, message):
        import requests

        username = settings.AFRICASTALKING_USERNAME
        api_key = settings.AFRICASTALKING_API_KEY
        if not api_key:
            logger.error('AFRICASTALKING_API_KEY not configured; cannot send SMS')
            return SMSResult(success=False, detail='SMS provider not configured')

        endpoint = self.SANDBOX_ENDPOINT if username == 'sandbox' else self.ENDPOINT
        data = {'username': username, 'to': to, 'message': message}
        if settings.AFRICASTALKING_SENDER_ID:
            data['from'] = settings.AFRICASTALKING_SENDER_ID

        try:
            resp = requests.post(
                endpoint,
                data=data,
                headers={
                    'apiKey': api_key,
                    'Accept': 'application/json',
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                timeout=15,
            )
            resp.raise_for_status()
        except Exception as exc:  # network/HTTP errors
            logger.exception('Africa\'s Talking SMS send failed: %s', exc)
            return SMSResult(success=False, detail='SMS delivery failed')

        return SMSResult(success=True, detail='sent')


def get_sms_backend():
    backend_cls = import_string(settings.SMS_BACKEND)
    return backend_cls()


def send_sms(to, message):
    return get_sms_backend().send(to, message)
