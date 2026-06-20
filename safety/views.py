from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from safety.models import TrustedContact
from safety.serializers import TrustedContactSerializer


class TrustedContactListCreateView(APIView):
    """GET /api/v1/contacts/  POST /api/v1/contacts/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=TrustedContactSerializer(many=True),
        parameters=[
            OpenApiParameter('type', OpenApiTypes.STR,
                             description='Filter by contact_type: FAMILY, FRIEND, EMERGENCY'),
        ],
        summary='List trusted contacts for the current user',
    )
    def get(self, request):
        qs = TrustedContact.objects.filter(owner=request.user)
        if ct := request.query_params.get('type'):
            qs = qs.filter(contact_type=ct.upper())
        return Response(TrustedContactSerializer(qs, many=True).data)

    @extend_schema(
        request=TrustedContactSerializer,
        responses={201: TrustedContactSerializer},
        summary='Add a trusted contact',
    )
    def post(self, request):
        ser = TrustedContactSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        contact = ser.save(owner=request.user)
        return Response(TrustedContactSerializer(contact).data, status=status.HTTP_201_CREATED)


class TrustedContactDetailView(APIView):
    """PATCH /api/v1/contacts/{id}/  DELETE /api/v1/contacts/{id}/"""
    permission_classes = [IsAuthenticated]

    def _get(self, pk, user):
        try:
            return TrustedContact.objects.get(id=pk, owner=user), None
        except TrustedContact.DoesNotExist:
            return None, Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)

    @extend_schema(responses=TrustedContactSerializer, summary='Retrieve a trusted contact')
    def get(self, request, pk):
        contact, err = self._get(pk, request.user)
        if err:
            return err
        return Response(TrustedContactSerializer(contact).data)

    @extend_schema(request=TrustedContactSerializer, responses=TrustedContactSerializer,
                   summary='Update a trusted contact')
    def patch(self, request, pk):
        contact, err = self._get(pk, request.user)
        if err:
            return err
        ser = TrustedContactSerializer(contact, data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        ser.save()
        return Response(ser.data)

    @extend_schema(responses={204: None}, summary='Remove a trusted contact')
    def delete(self, request, pk):
        contact, err = self._get(pk, request.user)
        if err:
            return err
        contact.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
