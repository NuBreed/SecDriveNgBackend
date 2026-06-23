from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from accounts.models import AuthEvent, Device


def _client_ip(request):
    if request is None:
        return None
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def _user_agent(request):
    if request is None:
        return ''
    return request.META.get('HTTP_USER_AGENT', '')[:512]


def log_event(event_type, user=None, request=None, identifier='', device_id='', **metadata):
    return AuthEvent.objects.create(
        user=user,
        event_type=event_type,
        identifier_tried=identifier or '',
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
        device_id=device_id or '',
        metadata=metadata or {},
    )


# ── Lockout ───────────────────────────────────────────────

def record_failed_login(user, request=None, identifier=''):
    """Increment failed-login counter and lock the account if over threshold."""
    log_event(AuthEvent.Type.LOGIN_FAILED, user=user, request=request, identifier=identifier)
    if user is None:
        return

    user.failed_login_count += 1
    max_attempts = getattr(settings, 'LOGIN_MAX_FAILED_ATTEMPTS', 5)
    if user.failed_login_count >= max_attempts:
        minutes = getattr(settings, 'LOGIN_LOCKOUT_MINUTES', 15)
        user.locked_until = timezone.now() + timedelta(minutes=minutes)
        user.failed_login_count = 0
        user.save(update_fields=['failed_login_count', 'locked_until'])
        log_event(AuthEvent.Type.LOCKOUT, user=user, request=request, identifier=identifier)
    else:
        user.save(update_fields=['failed_login_count'])


def clear_failures(user):
    if user.failed_login_count or user.locked_until:
        user.failed_login_count = 0
        user.locked_until = None
        user.save(update_fields=['failed_login_count', 'locked_until'])


# ── Devices ───────────────────────────────────────────────

def register_device(user, request=None, payload=None):
    """Upsert the device the user signed in from; sends new-device email if first seen."""
    payload = payload or {}
    device_id = (payload.get('device_id') or '').strip()
    if not device_id:
        return None

    device, created = Device.objects.update_or_create(
        user=user,
        device_id=device_id,
        defaults={
            'device_type': payload.get('device_type', '') or '',
            'platform': payload.get('platform', '') or '',
            'app_version': payload.get('app_version', '') or '',
            'is_active': True,
            'last_login_at': timezone.now(),
        },
    )

    if created and user.email:
        try:
            from notifications.email import send_new_device_login
            import datetime
            send_new_device_login(user, {
                'device_name': f"{payload.get('platform', 'Unknown')} — {payload.get('device_type', 'device')}",
                'ip': _client_ip(request) or 'Unknown',
                'time': datetime.datetime.now().strftime('%a %d %b %Y, %I:%M %p WAT'),
            })
        except Exception:
            pass

    return device


def revoke_device(user, device_id):
    Device.objects.filter(user=user, device_id=device_id).update(is_active=False)
