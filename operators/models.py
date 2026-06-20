"""Transport Operators & Fleet Management models (Epic 8)."""
import uuid

from django.db import models


class TransportOperator(models.Model):
    """An approved transport organization that manages participants and assets."""

    class BusinessType(models.TextChoices):
        BUS_COMPANY = 'BUS_COMPANY', 'Bus Company'
        TAXI = 'TAXI', 'Taxi Operator'
        KEKE = 'KEKE', 'Keke Association'
        OKADA = 'OKADA', 'Okada Association'
        SCHOOL_TRANSPORT = 'SCHOOL_TRANSPORT', 'School Transport'
        CORPORATE_SHUTTLE = 'CORPORATE_SHUTTLE', 'Corporate Shuttle'
        DELIVERY = 'DELIVERY', 'Delivery Company'
        LOGISTICS = 'LOGISTICS', 'Logistics Operator'
        GOVERNMENT_FLEET = 'GOVERNMENT_FLEET', 'Government Fleet'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='owned_operators',
    )
    verification = models.OneToOneField(
        'OperatorVerification', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='transport_operator',
    )
    organization_name = models.CharField(max_length=255)
    registration_number = models.CharField(max_length=100)
    business_type = models.CharField(max_length=32, choices=BusinessType.choices)
    contact_phone = models.CharField(max_length=30, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_address = models.TextField(blank=True)
    fleet_safety_score = models.FloatField(default=0.0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['owner']),
            models.Index(fields=['business_type', 'is_active']),
        ]

    def __str__(self):
        return f'{self.organization_name} ({self.business_type})'


class Branch(models.Model):
    """An organizational unit within a TransportOperator (HQ / regional / local)."""

    class BranchType(models.TextChoices):
        HEADQUARTERS = 'HQ', 'Headquarters'
        REGIONAL = 'REGIONAL', 'Regional Office'
        LOCAL = 'LOCAL', 'Local Branch'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operator = models.ForeignKey(
        TransportOperator, on_delete=models.CASCADE, related_name='branches',
    )
    parent = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children',
    )
    name = models.CharField(max_length=255)
    branch_type = models.CharField(max_length=16, choices=BranchType.choices, default=BranchType.LOCAL)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('operator', 'name')]
        ordering = ['branch_type', 'name']

    def __str__(self):
        return f'{self.operator.organization_name} — {self.name}'


class OperatorMembership(models.Model):
    """A user's role within a TransportOperator."""

    class Role(models.TextChoices):
        OWNER = 'OWNER', 'Owner'
        FLEET_MANAGER = 'FLEET_MANAGER', 'Fleet Manager'
        SAFETY_MANAGER = 'SAFETY_MANAGER', 'Safety Manager'
        OPERATIONS_MANAGER = 'OPERATIONS_MANAGER', 'Operations Manager'
        VIEWER = 'VIEWER', 'Viewer'

    # Roles that can mutate fleet state.
    WRITE_ROLES = {Role.OWNER, Role.FLEET_MANAGER, Role.OPERATIONS_MANAGER}
    # Roles that can access safety dashboards.
    SAFETY_ROLES = {Role.OWNER, Role.FLEET_MANAGER, Role.SAFETY_MANAGER}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operator = models.ForeignKey(
        TransportOperator, on_delete=models.CASCADE, related_name='memberships',
    )
    user = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='operator_memberships',
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='memberships',
    )
    role = models.CharField(max_length=24, choices=Role.choices, default=Role.VIEWER)
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('operator', 'user')]
        indexes = [models.Index(fields=['operator', 'role', 'is_active'])]

    def __str__(self):
        return f'{self.user} / {self.operator.organization_name} [{self.role}]'


class FleetParticipant(models.Model):
    """A driver, rider, or personnel member assigned to an operator's fleet."""

    class ParticipantType(models.TextChoices):
        DRIVER = 'DRIVER', 'Driver'
        RIDER = 'RIDER', 'Rider'
        OPERATOR_PERSONNEL = 'OPERATOR_PERSONNEL', 'Operator Personnel'

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        SUSPENDED = 'SUSPENDED', 'Suspended'
        REMOVED = 'REMOVED', 'Removed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operator = models.ForeignKey(
        TransportOperator, on_delete=models.CASCADE, related_name='participants',
    )
    user = models.ForeignKey(
        'accounts.User', on_delete=models.CASCADE, related_name='fleet_assignments',
    )
    driver = models.ForeignKey(
        'drivers.Driver', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='fleet_assignments',
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='participants',
    )
    participant_type = models.CharField(max_length=24, choices=ParticipantType.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    suspension_reason = models.TextField(blank=True)
    added_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fleet_participants_added',
    )
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('operator', 'user')]
        indexes = [
            models.Index(fields=['operator', 'status']),
            models.Index(fields=['operator', 'participant_type', 'status']),
        ]

    def __str__(self):
        return f'{self.user} → {self.operator.organization_name} [{self.participant_type}]'


class FleetAsset(models.Model):
    """A vehicle assigned to an operator's fleet."""

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        ASSIGNED = 'ASSIGNED', 'Assigned'
        RETIRED = 'RETIRED', 'Retired'
        REMOVED = 'REMOVED', 'Removed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operator = models.ForeignKey(
        TransportOperator, on_delete=models.CASCADE, related_name='assets',
    )
    vehicle = models.ForeignKey(
        'vehicles.Vehicle', on_delete=models.CASCADE, related_name='fleet_assignments',
    )
    branch = models.ForeignKey(
        Branch, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assets',
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    added_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='fleet_assets_added',
    )
    added_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('operator', 'vehicle')]
        indexes = [models.Index(fields=['operator', 'status'])]

    def __str__(self):
        return f'{self.vehicle} → {self.operator.organization_name}'


class ParticipantAssetAssignment(models.Model):
    """Tracks which participant is assigned to which asset (with history)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    participant = models.ForeignKey(
        FleetParticipant, on_delete=models.CASCADE, related_name='asset_assignments',
    )
    asset = models.ForeignKey(
        FleetAsset, on_delete=models.CASCADE, related_name='participant_assignments',
    )
    assigned_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='participant_asset_assignments',
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    unassigned_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=['participant', 'is_active']),
            models.Index(fields=['asset', 'is_active']),
        ]

    def __str__(self):
        return f'{self.participant.user} ↔ {self.asset.vehicle}'


class FleetSafetyScore(models.Model):
    """Computed safety score for a transport operator's fleet."""

    class Level(models.TextChoices):
        EXCELLENT = 'EXCELLENT', 'Excellent'
        GOOD = 'GOOD', 'Good'
        FAIR = 'FAIR', 'Fair'
        POOR = 'POOR', 'Poor'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operator = models.OneToOneField(
        TransportOperator, on_delete=models.CASCADE, related_name='safety_score',
    )
    score = models.FloatField(default=0.0)
    level = models.CharField(max_length=16, choices=Level.choices, default=Level.POOR)
    incident_factor = models.FloatField(default=0.0)
    deviation_factor = models.FloatField(default=0.0)
    compliance_factor = models.FloatField(default=0.0)
    performance_factor = models.FloatField(default=0.0)
    computed_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.operator.organization_name}: {self.score:.1f}/100 [{self.level}]'


# ── Legacy KYC model (kept from Epic 3) ──────────────────────────────────────

class OperatorVerification(models.Model):
    """Transport operator / organization verification."""

    class Status(models.TextChoices):
        PENDING = "PENDING"
        APPROVED = "APPROVED"
        REJECTED = "REJECTED"
        SUSPENDED = "SUSPENDED"

    user = models.OneToOneField(
        'accounts.User', on_delete=models.CASCADE, related_name='operator_verification',
    )
    organization_name = models.CharField(max_length=255)
    cac_number = models.CharField(max_length=100)
    contact_info = models.CharField(max_length=255, blank=True)
    certification_expiry = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING,
    )
    is_verified = models.BooleanField(default=False)
    rejection_reason = models.TextField(blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='operator_reviews',
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'OperatorVerification({self.organization_name}, {self.status})'
