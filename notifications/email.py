"""
HTML email delivery using Jinja2 templates.

Templates live in  templates/email/<name>.html
Each template receives a standard base context plus caller-supplied vars.
"""
import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

_BASE_CONTEXT = {
    'brand_name': 'SecDrive',
    'brand_color': '#1B3A6B',
    'accent_color': '#F59E0B',
    'brand_url': 'https://secdriveng.com',
    'support_email': 'support@secdriveng.com',
    'logo_url': 'https://secdriveng.com/assets/logo-email.png',
    'social_twitter': 'https://twitter.com/secdriveng',
    'social_instagram': 'https://instagram.com/secdriveng',
    'year': __import__('datetime').date.today().year,
}


def _render(template_name: str, context: dict) -> str:
    ctx = {**_BASE_CONTEXT, **context}
    return render_to_string(f'{template_name}.html', ctx, using='jinja2')


def send(
    to: str | list[str],
    subject: str,
    template: str,
    context: dict | None = None,
    from_email: str | None = None,
) -> bool:
    """Render *template* with *context* and send to *to*.

    Returns True on success, False on any failure (never raises).
    """
    recipients = [to] if isinstance(to, str) else to
    html = _render(template, context or {})
    msg = EmailMultiAlternatives(
        subject=subject,
        body=_strip_html(html),
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=recipients,
    )
    msg.attach_alternative(html, 'text/html')
    try:
        msg.send()
        return True
    except Exception as exc:
        logger.error('Email send failed to %s: %s', recipients, exc)
        return False


# ── Convenience senders for each auth touchpoint ─────────────────────────────

def send_otp_verification(user, otp_code: str) -> bool:
    return send(
        to=user.email,
        subject='Your SecDrive verification code',
        template='auth/otp_verification',
        context={
            'first_name': user.first_name or 'there',
            'otp_code': otp_code,
            'expiry_minutes': getattr(__import__('django.conf', fromlist=['settings']).settings, 'OTP_EXPIRY_MINUTES', 10),
        },
    )


def send_otp_password_reset(user, otp_code: str) -> bool:
    return send(
        to=user.email,
        subject='Reset your SecDrive password',
        template='auth/otp_password_reset',
        context={
            'first_name': user.first_name or 'there',
            'otp_code': otp_code,
            'expiry_minutes': getattr(__import__('django.conf', fromlist=['settings']).settings, 'OTP_EXPIRY_MINUTES', 10),
        },
    )


def send_welcome(user) -> bool:
    return send(
        to=user.email,
        subject='Welcome to SecDrive — you\'re all set!',
        template='auth/welcome',
        context={
            'first_name': user.first_name or 'there',
            'role': user.role,
        },
    )


def send_password_changed(user) -> bool:
    return send(
        to=user.email,
        subject='Your SecDrive password was changed',
        template='auth/password_changed',
        context={
            'first_name': user.first_name or 'there',
        },
    )


def send_new_device_login(user, device_info: dict) -> bool:
    return send(
        to=user.email,
        subject='New login detected on your SecDrive account',
        template='auth/new_device_login',
        context={
            'first_name': user.first_name or 'there',
            'device_name': device_info.get('device_name', 'Unknown device'),
            'ip_address': device_info.get('ip', ''),
            'login_time': device_info.get('time', ''),
        },
    )


def _strip_html(html: str) -> str:
    """Minimal HTML → plain-text fallback for email clients that block HTML."""
    import re
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
