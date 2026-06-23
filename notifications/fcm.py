"""
FCM push notification sender (Firebase Admin SDK).

Configuration (in Django settings / env):
  FIREBASE_CREDENTIALS_JSON         — path to service-account JSON file
  FIREBASE_CREDENTIALS_JSON_CONTENT — raw JSON string (for env-var deployments)

If neither is set, FCM is silently disabled — the app still works via WebSocket.
"""
import json
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

_app = None


def _get_app():
    global _app
    if _app is not None:
        return _app
    try:
        import firebase_admin
        from firebase_admin import credentials

        cred_path    = getattr(settings, 'FIREBASE_CREDENTIALS_JSON', None)
        cred_content = getattr(settings, 'FIREBASE_CREDENTIALS_JSON_CONTENT', None)

        if cred_content:
            cred = credentials.Certificate(json.loads(cred_content))
        elif cred_path:
            cred = credentials.Certificate(cred_path)
        else:
            logger.info('FCM: no credentials configured — push notifications disabled.')
            return None

        _app = firebase_admin.initialize_app(cred)
        logger.info('FCM: Firebase Admin SDK initialised.')
    except Exception as exc:
        logger.warning('FCM: init failed — %s', exc)
    return _app


def send_to_device(
    token: str,
    title: str,
    body: str,
    data: dict | None = None,
) -> bool:
    """Send a push notification to a single FCM registration token.

    Returns True on success, False on any failure (never raises).
    """
    if not token:
        return False
    app = _get_app()
    if app is None:
        return False

    try:
        from firebase_admin import messaging

        msg = messaging.Message(
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in (data or {}).items()},
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    sound='default',
                    priority='high',
                    visibility='public',
                ),
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(sound='default', badge=1),
                ),
            ),
            token=token,
        )
        messaging.send(msg, app=app)
        return True
    except Exception as exc:
        logger.warning('FCM send failed (token=…%s): %s', token[-6:], exc)
        return False
