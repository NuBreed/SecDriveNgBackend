from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateMediaStorage(FileSystemStorage):
    """Stores files outside the public MEDIA_ROOT with no public URL.

    Files saved here are never reachable at /media/; they are served only via
    the authenticated download endpoint (common.views.DocumentDownloadView).
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('location', settings.PRIVATE_MEDIA_ROOT)
        kwargs.setdefault('base_url', None)
        super().__init__(*args, **kwargs)


private_storage = PrivateMediaStorage()
