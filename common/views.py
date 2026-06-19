from django.http import FileResponse, Http404

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema
from drf_spectacular.types import OpenApiTypes

from common.models import VerificationDocument


class DocumentDownloadView(APIView):
    """Stream a privately-stored verification document.

    Access is limited to the document's owner and staff/admins — sensitive KYC
    documents are never exposed at a public /media/ URL.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.BINARY})
    def get(self, request, pk):
        try:
            doc = VerificationDocument.objects.get(pk=pk)
        except VerificationDocument.DoesNotExist:
            raise Http404

        if not (request.user.is_staff or doc.owner_id == request.user.id):
            # Don't reveal existence to non-owners.
            raise Http404

        try:
            return FileResponse(doc.file.open('rb'), as_attachment=False)
        except FileNotFoundError:
            raise Http404
