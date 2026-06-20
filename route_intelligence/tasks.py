"""Celery tasks for route intelligence — periodic monitoring (Story 2)."""
import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='route_intelligence.monitor_active_journeys')
def monitor_active_journeys():
    """Periodic task: run risk analysis on every active journey's last location.

    Runs on the Celery beat schedule. In tests, CELERY_TASK_ALWAYS_EAGER=True
    means it executes inline.
    """
    from journeys.models import Journey, JourneyLocation
    from route_intelligence.services import analyze_location

    journeys = Journey.objects.filter(status=Journey.Status.ACTIVE).prefetch_related('locations')
    count = 0
    for journey in journeys:
        loc = journey.last_location
        if loc is None:
            continue
        try:
            analyze_location(journey, loc)
            count += 1
        except Exception as exc:
            logger.exception('Risk analysis failed for journey %s: %s', journey.id, exc)

    logger.info('Route intelligence: analysed %d active journey(s)', count)
    return count


@shared_task(name='route_intelligence.analyze_journey_location')
def analyze_journey_location(journey_id: str, location_id: str):
    """Async task: run analysis for a single location ping.

    Called from ``journeys.services.record_location`` via ``on_commit``.
    """
    from journeys.models import Journey, JourneyLocation
    from route_intelligence.services import analyze_location

    try:
        journey = Journey.objects.get(id=journey_id)
        location = JourneyLocation.objects.get(id=location_id)
    except (Journey.DoesNotExist, JourneyLocation.DoesNotExist):
        logger.warning('analyze_journey_location: missing journey=%s or loc=%s',
                       journey_id, location_id)
        return

    try:
        analyze_location(journey, location)
    except Exception as exc:
        logger.exception('analyze_journey_location failed for %s: %s', journey_id, exc)
