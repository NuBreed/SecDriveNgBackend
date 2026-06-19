"""Trust score calculation.

Produces a 0-100 score from configurable factor weights
(``settings.TRUST_WEIGHTS``). Incident/complaint history are wired but evaluate
to 0 until those features land. Mirrors the iSafePass TrustService capping.
"""
from django.conf import settings


def _has_valid_documents(user):
    """True if the user has no expired verification documents on file."""
    docs = user.verification_documents.all()
    if not docs:
        return True
    return not any(d.is_expired for d in docs)


def _incident_score(user):
    # Placeholder until the incidents epic lands.
    return 0.0


def _complaint_score(user):
    # Placeholder until complaints land.
    return 0.0


def compute(user):
    """Return ``{'score': int, 'factors': {...}}`` for ``user``."""
    weights = settings.TRUST_WEIGHTS
    driver = getattr(user, 'driver', None)

    identity_verified = user.verification_level >= user.VerificationLevel.IDENTITY
    driver_verified = bool(driver and driver.verification_status == 'VERIFIED')
    owns_verified_vehicle = user.vehicles_owned.filter(is_verified=True).exists() \
        if hasattr(user, 'vehicles_owned') else False
    documents_valid = _has_valid_documents(user)

    factors = {
        'identity_verified': weights['identity_verified'] if identity_verified else 0,
        'driver_verified': weights['driver_verified'] if driver_verified else 0,
        'vehicle_verified': weights['vehicle_verified'] if owns_verified_vehicle else 0,
        'documents_valid': weights['documents_valid'] if documents_valid else 0,
        'incident_history': _incident_score(user) * weights['incident_history'],
        'complaint_history': _complaint_score(user) * weights['complaint_history'],
    }
    score = int(round(max(0, min(100, sum(factors.values())))))
    return {'score': score, 'factors': factors}


def recompute_and_store(user):
    """Recompute and persist the score on the user (and the Driver row)."""
    result = compute(user)
    user.trust_score = result['score']
    user.save(update_fields=['trust_score'])

    driver = getattr(user, 'driver', None)
    if driver is not None:
        driver.trust_score = result['score']
        driver.save(update_fields=['trust_score'])
    return result
