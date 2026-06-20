"""Celery tasks for fleet management (Epic 8)."""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='operators.compute_all_fleet_safety_scores')
def compute_all_fleet_safety_scores():
    """Periodic task: recompute fleet safety scores for all active operators."""
    from operators.models import TransportOperator
    from operators.services import compute_fleet_safety_score

    operators = TransportOperator.objects.filter(is_active=True)
    updated = 0
    for op in operators:
        try:
            compute_fleet_safety_score(op)
            updated += 1
        except Exception as exc:
            logger.exception('compute_all_fleet_safety_scores: failed for %s: %s', op.id, exc)
    logger.info('Fleet safety scores updated for %d operators', updated)
    return updated
