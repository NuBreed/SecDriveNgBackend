"""Celery tasks for accident detection & emergency escalation (Epic 7)."""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='accident_detection.auto_escalate_accident')
def auto_escalate_accident(event_id: str):
    """Fired after the confirmation countdown expires (Story 7).

    If the user has not confirmed safe, auto-escalates to iSafePass.
    """
    from accident_detection.services import auto_escalate_if_unconfirmed
    auto_escalate_if_unconfirmed(event_id)


@shared_task(name='accident_detection.retry_escalation')
def retry_escalation(escalation_id: str):
    """Retry a failed iSafePass delivery (Story 12)."""
    from accident_detection.models import EmergencyEscalation
    from accident_detection.services import _deliver_escalation

    try:
        esc = EmergencyEscalation.objects.get(id=escalation_id)
    except EmergencyEscalation.DoesNotExist:
        logger.warning('retry_escalation: escalation %s not found', escalation_id)
        return

    if esc.status == EmergencyEscalation.Status.DELIVERED:
        return  # already succeeded

    logger.info('Retrying escalation %s (attempt %d)', escalation_id, esc.retry_count + 1)
    _deliver_escalation(esc)


@shared_task(name='accident_detection.retry_pending_escalations')
def retry_pending_escalations():
    """Periodic task: find all RETRYING escalations whose retry time has arrived."""
    from django.utils import timezone
    from accident_detection.models import EmergencyEscalation
    from accident_detection.services import _deliver_escalation

    due = EmergencyEscalation.objects.filter(
        status=EmergencyEscalation.Status.RETRYING,
        next_retry_at__lte=timezone.now(),
    )
    for esc in due:
        try:
            _deliver_escalation(esc)
        except Exception as exc:
            logger.exception('retry_pending_escalations: failed for %s: %s', esc.id, exc)

    return due.count()
