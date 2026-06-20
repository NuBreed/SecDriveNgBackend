from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from places import services


class PlaceAutocompleteView(APIView):
    """GET /api/v1/places/autocomplete/?query=<text>&session_token=<token>"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter('query', OpenApiTypes.STR, required=True,
                             description='Partial place name / address'),
            OpenApiParameter('session_token', OpenApiTypes.STR, required=False,
                             description='Google session token for billing grouping'),
        ],
        responses={200: OpenApiTypes.OBJECT},
        summary='Autocomplete a place name via Google Places (server-proxied)',
    )
    def get(self, request):
        query = request.query_params.get('query', '').strip()
        if len(query) < 2:
            return Response([])
        session_token = request.query_params.get('session_token', '')
        predictions   = services.autocomplete(query, session_token=session_token)

        # Normalise to the shape the Flutter app expects.
        results = [
            {
                'place_id':    p.get('place_id', ''),
                'description': p.get('description', ''),
                'structured_formatting': {
                    'main_text':      p.get('structured_formatting', {}).get('main_text', ''),
                    'secondary_text': p.get('structured_formatting', {}).get('secondary_text', ''),
                },
            }
            for p in predictions
        ]
        return Response(results)
