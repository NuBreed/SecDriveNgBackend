from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import HelpArticle


class HelpArticleListView(APIView):
    """GET /api/v1/help/
    Returns all active help articles grouped by category.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        articles = HelpArticle.objects.filter(is_active=True)

        # Group by category preserving order.
        grouped: dict[str, list] = {}
        category_labels = dict(HelpArticle.CATEGORY_CHOICES)
        for a in articles:
            label = category_labels.get(a.category, a.category)
            grouped.setdefault(label, []).append({
                'id':       a.pk,
                'question': a.question,
                'answer':   a.answer,
                'order':    a.order,
            })

        return Response({
            'categories': [
                {'name': name, 'articles': items}
                for name, items in grouped.items()
            ],
        })
