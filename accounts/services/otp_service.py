from django.conf import settings
from django.utils import timezone

from accounts.models import OTP
from accounts.services.sms import send_sms


class OTPError(Exception):
    """Raised when an OTP cannot be issued or verified; carries a message."""


_MESSAGES = {
    OTP.Purpose.ACCOUNT_VERIFICATION: 'Your SecDrive verification code is {code}.',
    OTP.Purpose.PASSWORD_RESET: 'Your SecDrive password reset code is {code}.',
}


def can_resend(user, purpose):
    """Enforce a cooldown between OTP requests of the same purpose."""
    cooldown = getattr(settings, 'OTP_RESEND_COOLDOWN_SECONDS', 60)
    last = (
        OTP.objects.filter(user=user, purpose=purpose)
        .order_by('-created_at')
        .first()
    )
    if last is None:
        return True, 0
    elapsed = (timezone.now() - last.created_at).total_seconds()
    remaining = int(cooldown - elapsed)
    return (remaining <= 0), max(remaining, 0)


def issue_and_send(user, purpose, channel=OTP.Channel.SMS):
    """Create an OTP and deliver it via SMS (if phone on file) + email (if email on file).

    Returns (otp, dev_code_or_None).
    """
    record = OTP.generate_for(user, purpose, channel=channel)
    message = _MESSAGES[purpose].format(code=record.code)

    dev_code = None

    # ── SMS delivery ──────────────────────────────────────────────────
    if user.phone:
        result = send_sms(user.phone, message)
        if result.expose_code:
            dev_code = record.code
    else:
        dev_code = record.code

    # ── Email delivery ────────────────────────────────────────────────
    if user.email:
        try:
            from notifications.email import send_otp_verification, send_otp_password_reset
            if purpose == OTP.Purpose.ACCOUNT_VERIFICATION:
                send_otp_verification(user, record.code)
            elif purpose == OTP.Purpose.PASSWORD_RESET:
                send_otp_password_reset(user, record.code)
        except Exception:
            pass  # email failure never blocks the flow

    return record, dev_code


def verify(user, purpose, code):
    """Validate ``code`` for ``user``. Returns the OTP record or raises OTPError."""
    record = (
        OTP.objects.filter(user=user, purpose=purpose, is_used=False)
        .order_by('-created_at')
        .first()
    )
    if record is None:
        raise OTPError('No active code. Please request a new one.')

    max_attempts = getattr(settings, 'OTP_MAX_ATTEMPTS', 5)
    if record.attempts >= max_attempts:
        record.is_used = True
        record.save(update_fields=['is_used'])
        raise OTPError('Too many attempts. Please request a new code.')

    if record.is_expired:
        raise OTPError('Code has expired. Please request a new one.')

    if record.code != code:
        record.attempts += 1
        record.save(update_fields=['attempts'])
        raise OTPError('Invalid code.')

    record.is_used = True
    record.save(update_fields=['is_used'])
    return record
