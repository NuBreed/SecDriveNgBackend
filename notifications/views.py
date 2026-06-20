from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification, NotificationPreference


# ── In-app notifications ──────────────────────────────────────────────────────

class NotificationListView(APIView):
    """GET /api/v1/notifications/
    Returns up to 50 most recent notifications for the authenticated user.
    Accepts ?unread=true to filter unread only.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Notification.objects.filter(user=request.user)
        if request.query_params.get('unread') == 'true':
            qs = qs.filter(read=False)
        qs = qs[:50]
        data = [
            {
                'id':         str(n.id),
                'type':       n.type,
                'title':      n.title,
                'body':       n.body,
                'read':       n.read,
                'metadata':   n.metadata,
                'created_at': n.created_at.isoformat(),
            }
            for n in qs
        ]
        unread_count = Notification.objects.filter(user=request.user, read=False).count()
        return Response({'results': data, 'unread_count': unread_count})


class NotificationMarkReadView(APIView):
    """POST /api/v1/notifications/read/
    Body: {"ids": ["uuid", ...]}  — or omit ids to mark all as read.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        ids = request.data.get('ids')
        qs = Notification.objects.filter(user=request.user, read=False)
        if ids:
            qs = qs.filter(id__in=ids)
        updated = qs.update(read=True)
        return Response({'marked_read': updated})


# ── Notification preferences ──────────────────────────────────────────────────

class NotificationPrefsView(APIView):
    """GET /api/v1/notifications/prefs/   — fetch current preferences
    PATCH /api/v1/notifications/prefs/  — update one or more fields
    Supported fields: ride_alerts, sos_alerts, verification_alerts,
                      news_alerts, push_token
    """
    permission_classes = [IsAuthenticated]

    ALLOWED_FIELDS = {
        'ride_alerts', 'sos_alerts', 'verification_alerts',
        'news_alerts', 'push_token',
    }

    def _get_or_create(self, user):
        prefs, _ = NotificationPreference.objects.get_or_create(user=user)
        return prefs

    def get(self, request):
        prefs = self._get_or_create(request.user)
        return Response(self._serialize(prefs))

    def patch(self, request):
        prefs = self._get_or_create(request.user)
        fields_updated = []
        for field in self.ALLOWED_FIELDS:
            if field in request.data:
                setattr(prefs, field, request.data[field])
                fields_updated.append(field)
        if fields_updated:
            prefs.save(update_fields=fields_updated + ['updated_at'])
        return Response(self._serialize(prefs))

    @staticmethod
    def _serialize(prefs):
        return {
            'ride_alerts':          prefs.ride_alerts,
            'sos_alerts':           prefs.sos_alerts,
            'verification_alerts':  prefs.verification_alerts,
            'news_alerts':          prefs.news_alerts,
            'push_token':           prefs.push_token,
            'updated_at':           prefs.updated_at.isoformat(),
        }
