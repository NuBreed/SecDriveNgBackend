"""Derived verification badges shown on dashboards and the public verify page."""


def badges_for(user):
    badges = []
    if user.verification_level >= user.VerificationLevel.IDENTITY:
        badges.append('Identity Verified')
    driver = getattr(user, 'driver', None)
    if driver is not None and driver.verification_status == 'VERIFIED':
        badges.append('Verified Driver')
    return badges


def badges_for_vehicle(vehicle):
    badges = []
    if vehicle.is_verified:
        badges.append('Verified Vehicle')
    return badges
