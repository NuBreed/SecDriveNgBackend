from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from qr_codes.models import QRCode, QRScan


class QRCodeSerializer(serializers.ModelSerializer):
    entity_url = serializers.SerializerMethodField()

    class Meta:
        model = QRCode
        fields = [
            'id', 'entity_type', 'status', 'generation',
            'generated_at', 'revoked_at', 'revoke_reason', 'entity_url',
        ]
        read_only_fields = fields

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_entity_url(self, obj):
        request = self.context.get('request')
        entity = obj.content_object
        if entity is None or request is None:
            return None
        if obj.entity_type == QRCode.EntityType.PARTICIPANT:
            return request.build_absolute_uri(f'/api/v1/drivers/{entity.pk}/')
        return request.build_absolute_uri(f'/api/v1/vehicles/{entity.pk}/')


class QRScanSerializer(serializers.ModelSerializer):
    class Meta:
        model = QRScan
        fields = [
            'id', 'qr_code', 'scanned_by', 'result', 'token_tried',
            'ip_address', 'latitude', 'longitude', 'metadata', 'scanned_at',
        ]
        read_only_fields = fields


# ── Request serializers ────────────────────────────────────────────────────────

class AssetQRGenerateSerializer(serializers.Serializer):
    vehicle_id = serializers.IntegerField(
        help_text='Primary key of the Vehicle to generate a QR for.',
    )


class QRVerifySerializer(serializers.Serializer):
    token = serializers.CharField(
        help_text='Signed QR token from the QR code (participant or asset).',
    )
    asset_token = serializers.CharField(
        required=False, allow_blank=True,
        help_text='Optional: also verify an asset token in the same call (Story 6).',
    )
    latitude = serializers.FloatField(required=False, allow_null=True)
    longitude = serializers.FloatField(required=False, allow_null=True)


class QRRevokeSerializer(serializers.Serializer):
    reason = serializers.CharField(
        required=False, allow_blank=True, default='',
        help_text='Optional reason for revocation.',
    )


class QRRegenerateSerializer(serializers.Serializer):
    reason = serializers.CharField(
        required=False, allow_blank=True, default='Compromised QR',
        help_text='Reason for regenerating (old QR is revoked).',
    )
