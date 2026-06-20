from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from accounts.models import User
from safety.models import ContactInvite, TrustedContact
from safety.serializers import (
    AddTrustedSerializer,
    ContactInviteSerializer,
    InviteSerializer,
    PhoneCheckResultSerializer,
    PhoneCheckSerializer,
    TrustedContactSerializer,
)


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


# ── New endpoints ─────────────────────────────────────────────────────────────


class ContactCheckView(APIView):
    """POST /api/v1/contacts/check/

    Check whether a phone number is registered on SecDrive or iSafePass,
    and whether the caller has already added them as a trusted contact.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=PhoneCheckSerializer,
        responses={200: PhoneCheckResultSerializer},
        summary='Check if a phone number is on SecDrive / iSafePass',
    )
    def post(self, request):
        ser = PhoneCheckSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        phone = ser.validated_data['phone']

        # Normalise common Nigerian formats → +234…
        normalised = _normalise_phone(phone)

        # Look up the user by phone (try both formats).
        target = (
            User.objects.filter(phone=normalised).first()
            or User.objects.filter(phone=phone).first()
        )

        is_on_secdrive  = target is not None and target.role == User.Roles.PASSENGER
        # iSafePass flag stored on User — falls back to False if field absent.
        is_on_isafepass = getattr(target, 'isafepass_linked', False) if target else False

        is_already_trusted = (
            target is not None
            and TrustedContact.objects.filter(
                owner=request.user, phone__in=[phone, normalised]
            ).exists()
        )

        return Response({
            'is_on_secdrive':     is_on_secdrive,
            'is_on_isafepass':    is_on_isafepass,
            'is_already_trusted': is_already_trusted,
            'user_id':            str(target.uuid) if target else None,
        })


class AddTrustedContactView(APIView):
    """POST /api/v1/contacts/trusted/

    Add a user as a trusted contact by phone or user_id.
    Defaults to contact_type=FRIEND if not supplied.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=AddTrustedSerializer,
        responses={201: TrustedContactSerializer},
        summary='Add a trusted contact by phone or user_id',
    )
    def post(self, request):
        ser = AddTrustedSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        phone   = ser.validated_data.get('phone', '')
        user_id = ser.validated_data.get('user_id', '')

        # Resolve target user for display name.
        target = None
        if user_id:
            target = User.objects.filter(uuid=user_id).first()
        if not target and phone:
            normalised = _normalise_phone(phone)
            target = (
                User.objects.filter(phone=normalised).first()
                or User.objects.filter(phone=phone).first()
            )

        resolved_phone = phone or (target.phone if target else '')
        display_name   = (
            target.get_full_name() or target.username
            if target else resolved_phone
        )

        # Avoid duplicates.
        if TrustedContact.objects.filter(
            owner=request.user,
            phone__in=[resolved_phone, _normalise_phone(resolved_phone)],
        ).exists():
            return Response(
                {'detail': 'This contact is already in your trusted list.'},
                status=status.HTTP_409_CONFLICT,
            )

        contact = TrustedContact.objects.create(
            owner=request.user,
            name=display_name,
            phone=resolved_phone,
            contact_type=TrustedContact.ContactType.FRIEND,
            notify_on_journey=True,
        )
        return Response(
            TrustedContactSerializer(contact).data,
            status=status.HTTP_201_CREATED,
        )


class ContactInviteView(APIView):
    """GET  /api/v1/contacts/invite/  — list caller's outgoing invites
    POST /api/v1/contacts/invite/  — send / resend an invite
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={200: ContactInviteSerializer(many=True)},
        summary='List all outgoing invites for the current user',
    )
    def get(self, request):
        invites = (
            ContactInvite.objects
            .filter(inviter=request.user)
            .order_by('-created_at')
        )
        return Response(ContactInviteSerializer(invites, many=True).data)

    @extend_schema(
        request=InviteSerializer,
        responses={201: ContactInviteSerializer, 200: ContactInviteSerializer},
        summary='Send or resend an invite to a phone number',
    )
    def post(self, request):
        ser = InviteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        phone = ser.validated_data['phone']

        invite, created = ContactInvite.objects.get_or_create(
            inviter=request.user,
            phone=phone,
            defaults={'status': ContactInvite.Status.PENDING},
        )
        # Resend: bump status back to PENDING and refresh timestamp.
        if not created and invite.status in (
            ContactInvite.Status.EXPIRED,
            ContactInvite.Status.PENDING,
        ):
            invite.status = ContactInvite.Status.PENDING
            invite.save(update_fields=['status'])

        return Response(
            ContactInviteSerializer(invite).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalise_phone(phone: str) -> str:
    """Convert 0XXXXXXXXX → +234XXXXXXXXX (Nigerian numbers)."""
    p = phone.strip().replace(' ', '').replace('-', '')
    if p.startswith('0') and len(p) == 11:
        return '+234' + p[1:]
    return p
