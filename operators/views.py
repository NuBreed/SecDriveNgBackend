"""Operator views: KYC + Fleet Management (Epics 3 & 8)."""
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from drf_spectacular.utils import extend_schema
from drf_spectacular.types import OpenApiTypes

from operators import services
from operators.models import (
    Branch, FleetAsset, FleetParticipant, OperatorMembership,
    ParticipantAssetAssignment, TransportOperator,
)
from operators.serializers import (
    AddAssetSerializer, AssignParticipantSerializer, AssignToAssetSerializer,
    BranchSerializer, FleetAssetSerializer, FleetParticipantSerializer,
    FleetSafetyScoreSerializer, OperatorMembershipSerializer,
    OperatorVerificationSerializer, OperatorVerificationSubmitSerializer,
    ParticipantAssetAssignmentSerializer, TransportOperatorRegisterSerializer,
    TransportOperatorSerializer,
)
from vehicles.models import Vehicle


# ── Permission helpers ────────────────────────────────────────────────────────

def _get_operator(pk):
    try:
        return TransportOperator.objects.get(id=pk, is_active=True), None
    except TransportOperator.DoesNotExist:
        return None, Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)


def _membership(operator, user):
    return OperatorMembership.objects.filter(
        operator=operator, user=user, is_active=True,
    ).first()


def _require_write(operator, user):
    m = _membership(operator, user)
    if user.is_staff:
        return None
    if not m or m.role not in OperatorMembership.WRITE_ROLES:
        return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
    return None


def _require_read(operator, user):
    m = _membership(operator, user)
    if user.is_staff or m:
        return None
    return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)


# ── KYC verification views ────────────────────────────────────────────────────

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


# ── TransportOperator CRUD ────────────────────────────────────────────────────

class OperatorListCreateView(APIView):
    """
    GET  /api/v1/operators/      — list operators the user belongs to (or all for admin)
    POST /api/v1/operators/      — register a new transport operator (Story 1)
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=TransportOperatorSerializer(many=True), summary='List transport operators')
    def get(self, request):
        if request.user.is_staff:
            qs = TransportOperator.objects.filter(is_active=True)
        else:
            member_operator_ids = OperatorMembership.objects.filter(
                user=request.user, is_active=True,
            ).values_list('operator_id', flat=True)
            qs = TransportOperator.objects.filter(id__in=member_operator_ids, is_active=True)
        return Response(TransportOperatorSerializer(qs, many=True).data)

    @extend_schema(
        request=TransportOperatorRegisterSerializer,
        responses={201: TransportOperatorSerializer},
        summary='Register a transport operator (Story 1)',
    )
    def post(self, request):
        ser = TransportOperatorRegisterSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data

        # Link to verified KYC if present.
        verification_obj = getattr(request.user, 'operator_verification', None)
        if verification_obj and not verification_obj.is_verified:
            verification_obj = None

        op = services.register_operator(
            user=request.user,
            organization_name=vd['organization_name'],
            registration_number=vd['registration_number'],
            business_type=vd['business_type'],
            contact_phone=vd.get('contact_phone', ''),
            contact_email=vd.get('contact_email', ''),
            contact_address=vd.get('contact_address', ''),
            verification_obj=verification_obj,
        )
        return Response(TransportOperatorSerializer(op).data, status=status.HTTP_201_CREATED)


class OperatorDetailView(APIView):
    """GET /api/v1/operators/{id}/ — retrieve operator detail."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=TransportOperatorSerializer, summary='Retrieve a transport operator')
    def get(self, request, pk):
        op, err = _get_operator(pk)
        if err:
            return err
        err = _require_read(op, request.user)
        if err:
            return err
        return Response(TransportOperatorSerializer(op).data)


# ── Participants (Story 3) ────────────────────────────────────────────────────

class ParticipantListView(APIView):
    """
    GET  /api/v1/operators/{id}/participants/  — list fleet participants
    POST /api/v1/operators/{id}/participants/  — assign a participant
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=FleetParticipantSerializer(many=True), summary='List fleet participants')
    def get(self, request, pk):
        op, err = _get_operator(pk)
        if err:
            return err
        err = _require_read(op, request.user)
        if err:
            return err
        participant_status = request.query_params.get('status')
        qs = FleetParticipant.objects.filter(operator=op).select_related('user', 'driver', 'branch')
        if participant_status:
            qs = qs.filter(status=participant_status)
        return Response(FleetParticipantSerializer(qs, many=True).data)

    @extend_schema(
        request=AssignParticipantSerializer,
        responses={201: FleetParticipantSerializer},
        summary='Assign a participant to the fleet (Story 3)',
    )
    def post(self, request, pk):
        op, err = _get_operator(pk)
        if err:
            return err
        err = _require_write(op, request.user)
        if err:
            return err
        ser = AssignParticipantSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data

        try:
            from accounts.models import User
            participant_user = User.objects.get(id=vd['user_id'])
        except Exception:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        branch = None
        if vd.get('branch_id'):
            try:
                branch = Branch.objects.get(id=vd['branch_id'], operator=op)
            except Branch.DoesNotExist:
                return Response({'detail': 'Branch not found.'}, status=status.HTTP_404_NOT_FOUND)

        participant = services.assign_participant(
            op, participant_user, vd['participant_type'], branch=branch, added_by=request.user,
        )
        return Response(FleetParticipantSerializer(participant).data, status=status.HTTP_201_CREATED)


class ParticipantDetailView(APIView):
    """
    DELETE /api/v1/operators/{id}/participants/{pid}/  — remove participant
    PATCH  /api/v1/operators/{id}/participants/{pid}/  — suspend participant
    """
    permission_classes = [IsAuthenticated]

    def _get_participant(self, pk, pid):
        op, err = _get_operator(pk)
        if err:
            return None, None, err
        try:
            p = FleetParticipant.objects.get(id=pid, operator=op)
        except FleetParticipant.DoesNotExist:
            return None, None, Response({'detail': 'Participant not found.'}, status=status.HTTP_404_NOT_FOUND)
        return op, p, None

    @extend_schema(
        request=None,
        responses={200: FleetParticipantSerializer},
        summary='Suspend a fleet participant (Story 3)',
    )
    def patch(self, request, pk, pid):
        op, participant, err = self._get_participant(pk, pid)
        if err:
            return err
        err = _require_write(op, request.user)
        if err:
            return err
        reason = request.data.get('reason', '')
        updated = services.suspend_participant(participant, reason)
        return Response(FleetParticipantSerializer(updated).data)

    @extend_schema(request=None, responses={204: None}, summary='Remove a fleet participant (Story 3)')
    def delete(self, request, pk, pid):
        op, participant, err = self._get_participant(pk, pid)
        if err:
            return err
        err = _require_write(op, request.user)
        if err:
            return err
        services.remove_participant(participant)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Assets (Story 4) ─────────────────────────────────────────────────────────

class AssetListView(APIView):
    """
    GET  /api/v1/operators/{id}/assets/  — list fleet assets
    POST /api/v1/operators/{id}/assets/  — add an asset
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=FleetAssetSerializer(many=True), summary='List fleet assets')
    def get(self, request, pk):
        op, err = _get_operator(pk)
        if err:
            return err
        err = _require_read(op, request.user)
        if err:
            return err
        asset_status = request.query_params.get('status')
        qs = FleetAsset.objects.filter(operator=op).select_related('vehicle', 'branch')
        if asset_status:
            qs = qs.filter(status=asset_status)
        return Response(FleetAssetSerializer(qs, many=True).data)

    @extend_schema(
        request=AddAssetSerializer,
        responses={201: FleetAssetSerializer},
        summary='Add a vehicle to the fleet (Story 4)',
    )
    def post(self, request, pk):
        op, err = _get_operator(pk)
        if err:
            return err
        err = _require_write(op, request.user)
        if err:
            return err
        ser = AddAssetSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data

        try:
            vehicle = Vehicle.objects.get(id=vd['vehicle_id'])
        except Vehicle.DoesNotExist:
            return Response({'detail': 'Vehicle not found.'}, status=status.HTTP_404_NOT_FOUND)

        branch = None
        if vd.get('branch_id'):
            try:
                branch = Branch.objects.get(id=vd['branch_id'], operator=op)
            except Branch.DoesNotExist:
                return Response({'detail': 'Branch not found.'}, status=status.HTTP_404_NOT_FOUND)

        asset = services.add_fleet_asset(op, vehicle, branch=branch, added_by=request.user)
        return Response(FleetAssetSerializer(asset).data, status=status.HTTP_201_CREATED)


class AssetDetailView(APIView):
    """
    DELETE /api/v1/operators/{id}/assets/{aid}/         — remove asset
    PATCH  /api/v1/operators/{id}/assets/{aid}/         — retire asset
    POST   /api/v1/operators/{id}/assets/{aid}/assign/  — assign participant to asset
    """
    permission_classes = [IsAuthenticated]

    def _get_asset(self, pk, aid):
        op, err = _get_operator(pk)
        if err:
            return None, None, err
        try:
            asset = FleetAsset.objects.get(id=aid, operator=op)
        except FleetAsset.DoesNotExist:
            return None, None, Response({'detail': 'Asset not found.'}, status=status.HTTP_404_NOT_FOUND)
        return op, asset, None

    @extend_schema(request=None, responses={200: FleetAssetSerializer}, summary='Retire a fleet asset (Story 4)')
    def patch(self, request, pk, aid):
        op, asset, err = self._get_asset(pk, aid)
        if err:
            return err
        err = _require_write(op, request.user)
        if err:
            return err
        updated = services.retire_fleet_asset(asset)
        return Response(FleetAssetSerializer(updated).data)

    @extend_schema(request=None, responses={204: None}, summary='Remove a fleet asset (Story 4)')
    def delete(self, request, pk, aid):
        op, asset, err = self._get_asset(pk, aid)
        if err:
            return err
        err = _require_write(op, request.user)
        if err:
            return err
        services.remove_fleet_asset(asset)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AssetAssignView(APIView):
    """POST /api/v1/operators/{id}/assets/{aid}/assign/ — assign participant to asset (Story 5)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=AssignToAssetSerializer,
        responses={201: ParticipantAssetAssignmentSerializer},
        summary='Assign a participant to an asset (Story 5)',
    )
    def post(self, request, pk, aid):
        op, err = _get_operator(pk)
        if err:
            return err
        err = _require_write(op, request.user)
        if err:
            return err
        try:
            asset = FleetAsset.objects.get(id=aid, operator=op)
        except FleetAsset.DoesNotExist:
            return Response({'detail': 'Asset not found.'}, status=status.HTTP_404_NOT_FOUND)

        ser = AssignToAssetSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            participant = FleetParticipant.objects.get(
                id=ser.validated_data['participant_id'], operator=op,
            )
        except FleetParticipant.DoesNotExist:
            return Response({'detail': 'Participant not found.'}, status=status.HTTP_404_NOT_FOUND)

        if participant.status != FleetParticipant.Status.ACTIVE:
            return Response(
                {'detail': 'Only active participants can be assigned to assets.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        assignment = services.assign_participant_to_asset(participant, asset, request.user)
        return Response(
            ParticipantAssetAssignmentSerializer(assignment).data, status=status.HTTP_201_CREATED,
        )


# ── Fleet dashboard, tracking, safety, compliance, analytics ─────────────────

class FleetDashboardView(APIView):
    """GET /api/v1/operators/{id}/fleet/ — fleet overview (Stories 6-10)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, summary='Fleet dashboard (Stories 6-10)')
    def get(self, request, pk):
        op, err = _get_operator(pk)
        if err:
            return err
        err = _require_read(op, request.user)
        if err:
            return err
        include = request.query_params.getlist('include')
        data = services.get_fleet_dashboard(op)
        if not include or 'live' in include:
            data['live_journeys'] = services.get_live_fleet(op)
        if not include or 'safety' in include:
            data['safety_monitoring'] = services.get_safety_monitoring(op)
        if not include or 'compliance' in include:
            data['compliance'] = services.get_compliance_status(op)
        return Response(data)


class FleetAnalyticsView(APIView):
    """GET /api/v1/operators/{id}/analytics/ — operational analytics (Story 11)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: OpenApiTypes.OBJECT}, summary='Fleet analytics (Story 11)')
    def get(self, request, pk):
        op, err = _get_operator(pk)
        if err:
            return err
        err = _require_read(op, request.user)
        if err:
            return err
        days = int(request.query_params.get('days', 30))
        days = min(max(days, 1), 365)
        return Response(services.get_analytics(op, days=days))


class FleetSafetyScoreView(APIView):
    """GET /api/v1/operators/{id}/safety-score/ — fleet safety score (Story 14)."""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=FleetSafetyScoreSerializer, summary='Fleet safety score (Story 14)')
    def get(self, request, pk):
        op, err = _get_operator(pk)
        if err:
            return err
        err = _require_read(op, request.user)
        if err:
            return err
        fss = services.compute_fleet_safety_score(op)
        return Response(FleetSafetyScoreSerializer(fss).data)


# ── Branches (Story 12) ───────────────────────────────────────────────────────

class BranchListView(APIView):
    """GET/POST /api/v1/operators/{id}/branches/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=BranchSerializer(many=True), summary='List branches (Story 12)')
    def get(self, request, pk):
        op, err = _get_operator(pk)
        if err:
            return err
        err = _require_read(op, request.user)
        if err:
            return err
        return Response(BranchSerializer(op.branches.filter(is_active=True), many=True).data)

    @extend_schema(request=BranchSerializer, responses={201: BranchSerializer}, summary='Create branch (Story 12)')
    def post(self, request, pk):
        op, err = _get_operator(pk)
        if err:
            return err
        err = _require_write(op, request.user)
        if err:
            return err
        ser = BranchSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        vd = ser.validated_data
        branch = services.create_branch(
            op,
            name=vd['name'],
            branch_type=vd.get('branch_type', 'LOCAL'),
            parent=vd.get('parent'),
            address=vd.get('address', ''),
            phone=vd.get('phone', ''),
        )
        return Response(BranchSerializer(branch).data, status=status.HTTP_201_CREATED)


# ── Members (Story 13) ────────────────────────────────────────────────────────

class MemberListView(APIView):
    """GET/POST /api/v1/operators/{id}/members/"""
    permission_classes = [IsAuthenticated]

    @extend_schema(responses=OperatorMembershipSerializer(many=True), summary='List operator members (Story 13)')
    def get(self, request, pk):
        op, err = _get_operator(pk)
        if err:
            return err
        err = _require_read(op, request.user)
        if err:
            return err
        qs = OperatorMembership.objects.filter(operator=op, is_active=True).select_related('user', 'branch')
        return Response(OperatorMembershipSerializer(qs, many=True).data)

    @extend_schema(
        request=OperatorMembershipSerializer,
        responses={201: OperatorMembershipSerializer},
        summary='Add or update an operator member role (Story 13)',
    )
    def post(self, request, pk):
        op, err = _get_operator(pk)
        if err:
            return err
        err = _require_write(op, request.user)
        if err:
            return err
        # Only OWNER can grant OWNER role.
        m = _membership(op, request.user)
        role = request.data.get('role', OperatorMembership.Role.VIEWER)
        if role == OperatorMembership.Role.OWNER:
            is_owner = m and m.role == OperatorMembership.Role.OWNER
            if not is_owner and not request.user.is_staff:
                return Response(
                    {'detail': 'Only the owner can grant the OWNER role.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
        try:
            from accounts.models import User
            target_user = User.objects.get(id=request.data.get('user'))
        except Exception:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        branch = None
        if request.data.get('branch'):
            try:
                branch = Branch.objects.get(id=request.data['branch'], operator=op)
            except Branch.DoesNotExist:
                return Response({'detail': 'Branch not found.'}, status=status.HTTP_404_NOT_FOUND)

        membership = services.add_member(op, target_user, role=role, branch=branch)
        return Response(OperatorMembershipSerializer(membership).data, status=status.HTTP_201_CREATED)


# ── Admin views ───────────────────────────────────────────────────────────────

class AdminOperatorListView(APIView):
    """GET /api/v1/admin/operators/ — all operators for platform admin."""
    permission_classes = [IsAdminUser]

    @extend_schema(responses=TransportOperatorSerializer(many=True), summary='All transport operators (admin)')
    def get(self, request):
        qs = TransportOperator.objects.all().select_related('owner', 'verification')
        op_status = request.query_params.get('status')
        if op_status == 'verified':
            qs = qs.filter(verification__is_verified=True)
        elif op_status == 'unverified':
            qs = qs.filter(verification__isnull=True)
        return Response(TransportOperatorSerializer(qs, many=True).data)
