from notifications.models import Notification


def notify(user, title, body='', type=Notification.Type.GENERAL, **metadata):
    """Create an in-app notification for a user."""
    return Notification.objects.create(
        user=user, type=type, title=title, body=body, metadata=metadata or {},
    )
