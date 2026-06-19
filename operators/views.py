from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema

from operators.serializers import (
    OperatorVerificationSubmitSerializer,
    OperatorVerificationSerializer,
)
from operators import services


class OperatorVerificationView(APIView):
    """POST /api/v1/operators/verification/ — submit organization KYC."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request=OperatorVerificationSubmitSerializer, responses=OperatorVerificationSerializer)
    def post(self, request):
        serializer = OperatorVerificationSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vd = serializer.validated_data
        req = services.submit_operator_verification(
            request.user,
            organization_name=vd['organization_name'],
            cac_number=vd['cac_number'],
            contact_info=vd.get('contact_info', ''),
            cac_certificate=vd['cac_certificate'],
            proof_of_address=vd['proof_of_address'],
            representative_id=vd['representative_id'],
            certification_expiry=vd.get('certification_expiry'),
        )
        return Response(OperatorVerificationSerializer(req).data, status=status.HTTP_201_CREATED)


class OperatorVerificationStatusView(APIView):
    """GET /api/v1/operators/verification/status/."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=OperatorVerificationSerializer)
    def get(self, request):
        req = getattr(request.user, 'operator_verification', None)
        if req is None:
            return Response({'status': 'NOT_SUBMITTED'})
        return Response(OperatorVerificationSerializer(req).data)
