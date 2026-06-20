"""Auto-accept pending ContactInvites when the invited user verifies."""
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from accounts.models import User


@receiver(post_save, sender=User)
def accept_pending_invites(sender, instance: User, created: bool, **kwargs):
    """When a user's phone is verified, fulfil any pending invites for that number."""
    # Only act when the user becomes verified and has a phone number.
    if not instance.is_verified or not instance.phone:
        return

    # Import here to avoid circular imports.
    from safety.models import ContactInvite, TrustedContact

    phone      = instance.phone
    normalised = _normalise(phone)

    pending = ContactInvite.objects.filter(
        phone__in=[phone, normalised],
        status=ContactInvite.Status.PENDING,
    ).select_related('inviter')

    if not pending.exists():
        return

    with transaction.atomic():
        for invite in pending:
            # Skip if the inviter already has them as a trusted contact.
            already_exists = TrustedContact.objects.filter(
                owner=invite.inviter,
                phone__in=[phone, normalised],
            ).exists()

            if not already_exists:
                TrustedContact.objects.create(
                    owner=invite.inviter,
                    name=instance.get_full_name() or instance.username,
                    phone=phone,
                    contact_type=TrustedContact.ContactType.FRIEND,
                    notify_on_journey=True,
                )

            invite.status      = ContactInvite.Status.ACCEPTED
            invite.invited_user = instance
            invite.accepted_at = timezone.now()
            invite.save(update_fields=['status', 'invited_user', 'accepted_at'])

            # TODO: send push notification to inviter that their contact joined.


def _normalise(phone: str) -> str:
    p = phone.strip().replace(' ', '').replace('-', '')
    if p.startswith('0') and len(p) == 11:
        return '+234' + p[1:]
    return p
