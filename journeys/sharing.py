"""Journey sharing service.

Responsibilities
----------------
- Create / update JourneyShare records (Stories 4-5).
- Generate / revoke TrackingLink records (Story 6).
- Send notifications to recipients (Stories 5, 10, 12).
- Trigger the iSafePass subscription (Story 7) — best-effort; never blocks journey.
- Push real-time WebSocket events to the per-user notifications channel.
"""
import logging

from django.core import signing
from django.db import transaction
from django.utils import timezone

from journeys.models import Journey, JourneyShare, TrackingLink
from notifications.services import notify

logger = logging.getLogger(__name__)

_TRACKING_SALT = 'secdrive.tracking'


# ─── helpers ──────────────────────────────────────────────────────────────────

def _push(user_pk, event, data):
    """Best-effort Channels push to the user's notification channel."""
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        layer = get_channel_layer()
        if layer is None:
            return
        async_to_sync(layer.group_send)(
            f'notifications_{user_pk}',
            {'type': 'notification.message', 'event': event, 'data': data},
        )
    except Exception:
        pass


def _journey_summary(journey, privacy=None):
    priv = privacy or {}
    summary = {'journey_id': str(journey.id), 'status': journey.status}
    if priv.get('show_name', True):
        u = journey.passenger
        summary['passenger_name'] = f'{u.first_name} {u.last_name}'.strip() or u.username
    if priv.get('show_participant', True):
        d = journey.driver
        du = d.user
        summary['participant'] = {
            'name': f'{du.first_name} {du.last_name}'.strip() or du.username,
            'type': d.participant_type,
        }
    if priv.get('show_asset', True):
        v = journey.vehicle
        summary['asset'] = {
            'registration': v.registration_number,
            'description': f'{v.brand} {v.model} ({v.year})',
        }
    return summary


# ─── sharing (Stories 4-5) ────────────────────────────────────────────────────

@transaction.atomic
def share_journey(journey, contact_ids: list, privacy_overrides: dict = None) -> list:
    """Create or reactivate JourneyShare records for the given contact IDs.

    Returns the list of JourneyShare objects created/updated.
    """
    from safety.models import TrustedContact
    privacy_overrides = privacy_overrides or {}

    contacts = TrustedContact.objects.filter(
        id__in=contact_ids, owner=journey.passenger,
    )
    shares = []
    for contact in contacts:
        priv = privacy_overrides.get(str(contact.id), {})
        share, created = JourneyShare.objects.get_or_create(
            journey=journey, contact=contact,
            defaults={'privacy': priv, 'active': True},
        )
        if not created:
            share.active = True
            share.privacy = priv
            share.unshared_at = None
            share.save(update_fields=['active', 'privacy', 'unshared_at'])
        shares.append(share)

    return shares


@transaction.atomic
def unshare_journey(journey, contact_ids: list = None) -> int:
    """Deactivate shares.  If contact_ids is None, unshare all."""
    qs = JourneyShare.objects.filter(journey=journey, active=True)
    if contact_ids is not None:
        qs = qs.filter(contact_id__in=contact_ids)
    count = qs.update(active=False, unshared_at=timezone.now())
    return count


def notify_recipients(journey, event: str, extra: dict = None):
    """Send an in-app notification + WS push to all active share recipients."""
    shares = JourneyShare.objects.filter(
        journey=journey, active=True,
    ).select_related('contact__owner')

    titles = {
        'journey.started': '🚗 Journey started',
        'journey.paused': '⏸ Journey paused',
        'journey.resumed': '▶ Journey resumed',
        'journey.completed': '✅ Journey completed',
        'journey.cancelled': '❌ Journey cancelled',
        'journey.shared': 'A journey has been shared with you',
        'journey.alert': '⚠️ Journey alert',
        'journey.sos': '🆘 SOS — passenger needs help',
    }
    # Collect unique owner PKs to avoid duplicate notifications.
    notified = set()
    for share in shares:
        owner = share.contact.owner
        if owner.pk in notified:
            continue
        notified.add(owner.pk)
        priv = share.get_privacy()
        data = {**_journey_summary(journey, priv), **(extra or {})}
        notify(
            owner,
            title=titles.get(event, 'Journey update'),
            body=data.get('message', ''),
            type='JOURNEY_UPDATE',
            journey_id=str(journey.id),
            event=event,
        )
        _push(owner.pk, event, data)


# ─── journey start — one-shot orchestration ───────────────────────────────────

def on_journey_started(journey):
    """Called by journeys.services.start_journey after the DB write.

    1. Auto-share with contacts that have notify_on_journey=True.
    2. Generate a tracking link.
    3. Notify all recipients.
    4. Subscribe to iSafePass (best-effort).
    """
    from safety.models import TrustedContact

    # Auto-share with all notify_on_journey contacts.
    contact_ids = list(
        TrustedContact.objects.filter(
            owner=journey.passenger, notify_on_journey=True,
        ).values_list('id', flat=True)
    )
    if contact_ids:
        share_journey(journey, contact_ids)

    # Generate a tracking link.
    link = generate_tracking_link(journey, journey.passenger)

    # Notify recipients.
    notify_recipients(journey, 'journey.started', {
        'tracking_url': tracking_url(link.token),
        'message': 'A journey you are monitoring has started.',
    })

    # iSafePass subscription — best-effort.
    _subscribe_isafepass(journey)


def on_journey_event(journey, event: str, extra: dict = None):
    """Notify recipients of any lifecycle event post-start."""
    notify_recipients(journey, event, extra)


# ─── tracking link (Story 6) ──────────────────────────────────────────────────

@transaction.atomic
def generate_tracking_link(journey, user, expires_hours=24) -> TrackingLink:
    """Create a new signed tracking link for this journey."""
    from datetime import timedelta
    link_id = None
    # Placeholder: create with empty token first, then fill in the signed value
    # so the PK is known before signing.
    link = TrackingLink.objects.create(
        journey=journey, created_by=user,
        expires_at=timezone.now() + timedelta(hours=expires_hours),
        token='__placeholder__',
    )
    token = signing.dumps(
        {'journey_id': str(journey.id), 'link_id': str(link.id)},
        salt=_TRACKING_SALT,
    )
    link.token = token
    link.save(update_fields=['token'])
    return link


def tracking_url(token: str) -> str:
    from django.conf import settings
    base = settings.PUBLIC_BASE_URL.rstrip('/')
    return f'{base}/api/v1/tracking/{token}/'


def resolve_tracking_link(token: str) -> TrackingLink | None:
    """Decode a tracking token and return the active link, or None."""
    try:
        data = signing.loads(token, salt=_TRACKING_SALT, max_age=86400 * 7)
    except signing.BadSignature:
        return None
    try:
        link = TrackingLink.objects.select_related('journey').get(id=data['link_id'])
    except TrackingLink.DoesNotExist:
        return None
    return link if link.is_valid else None


# ─── iSafePass subscription (Story 7) ────────────────────────────────────────

def _subscribe_isafepass(journey):
    """Subscribe journey to iSafePass safety monitoring — best-effort."""
    from integrations.models import JourneySubscription
    from integrations.services.isafepass_bridge import get_bridge, ISafePassUnavailable

    sub, _ = JourneySubscription.objects.get_or_create(journey=journey)
    if sub.status == JourneySubscription.Status.ACTIVE:
        return sub

    bridge = get_bridge()
    if not bridge.enabled:
        sub.status = JourneySubscription.Status.FAILED
        sub.error_message = 'iSafePass bridge not configured.'
        sub.save(update_fields=['status', 'error_message'])
        return sub

    try:
        result = bridge.subscribe_journey(journey)
        sub.isafepass_subscription_id = result.get('subscription_id', '')
        sub.status = JourneySubscription.Status.ACTIVE
        sub.response_data = result
        sub.save(update_fields=['isafepass_subscription_id', 'status', 'response_data'])
    except ISafePassUnavailable as exc:
        sub.status = JourneySubscription.Status.FAILED
        sub.error_message = str(exc)
        sub.save(update_fields=['status', 'error_message'])
        logger.warning('iSafePass subscription failed for journey %s: %s', journey.id, exc)
    return sub


def unsubscribe_isafepass(journey):
    """Close the iSafePass subscription when a journey ends."""
    from integrations.models import JourneySubscription
    from integrations.services.isafepass_bridge import get_bridge, ISafePassUnavailable
    try:
        sub = journey.isafepass_subscription
    except JourneySubscription.DoesNotExist:
        return
    if sub.status != JourneySubscription.Status.ACTIVE:
        return
    bridge = get_bridge()
    if not bridge.enabled:
        return
    try:
        bridge.unsubscribe_journey(sub.isafepass_subscription_id)
        sub.status = JourneySubscription.Status.CLOSED
        sub.closed_at = timezone.now()
        sub.save(update_fields=['status', 'closed_at'])
    except ISafePassUnavailable as exc:
        logger.warning('iSafePass unsubscribe failed: %s', exc)
