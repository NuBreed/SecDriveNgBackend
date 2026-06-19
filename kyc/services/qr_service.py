"""Signed verification QR codes.

A QR encodes the public verify URL carrying a signed token (entity type + id).
Only verified+valid entities are issued a QR. The token is signed with
``SECRET_KEY`` so it cannot be forged; the public verify endpoint reads back the
current verification status.
"""
import io

from django.conf import settings
from django.core import signing

SALT = 'secdrive.verify'
SALT_V2 = 'secdrive.qr.v2'


def make_token(entity_type, entity_id):
    return signing.dumps({'t': entity_type, 'id': str(entity_id)}, salt=SALT)


def read_token(token, max_age=None):
    """Return ``{'t': ..., 'id': ...}`` or raise signing.BadSignature."""
    return signing.loads(token, salt=SALT, max_age=max_age)


def make_token_v2(qr_uuid, entity_type, entity_id):
    """V2 token — includes the QRCode record UUID so the verify endpoint can
    look up revocation status without trusting the payload alone."""
    return signing.dumps(
        {'v': 2, 'qr': str(qr_uuid), 't': entity_type, 'id': str(entity_id)},
        salt=SALT_V2,
    )


def read_token_v2(token):
    """Return v2 payload or raise signing.BadSignature."""
    return signing.loads(token, salt=SALT_V2)


def verify_url(token):
    base = settings.PUBLIC_BASE_URL.rstrip('/')
    return f'{base}/api/v1/verify/{token}/'


def render_png(token):
    """Return PNG bytes of a QR encoding the public verify URL."""
    import qrcode

    img = qrcode.make(verify_url(token))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()
