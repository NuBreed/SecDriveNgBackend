from rest_framework import serializers

from common.models import VerificationDocument
from kyc.models import IdentityVerification


class IdentitySubmitSerializer(serializers.Serializer):
    primary_id_type = serializers.ChoiceField(choices=IdentityVerification.IDType.choices)
    id_document = serializers.FileField()
    document_number = serializers.CharField(required=False, allow_blank=True)
    selfie = serializers.ImageField(required=False)


class SelfieSerializer(serializers.Serializer):
    selfie = serializers.ImageField()


class IdentityVerificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = IdentityVerification
        fields = [
            'id', 'primary_id_type', 'status', 'rejection_reason',
            'submitted_at', 'reviewed_at', 'updated_at',
        ]
        read_only_fields = fields


class VerificationDocumentSerializer(serializers.ModelSerializer):
    download_url = serializers.SerializerMethodField()
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = VerificationDocument
        fields = [
            'id', 'doc_type', 'document_number', 'expiry_date',
            'is_expired', 'uploaded_at', 'download_url',
        ]

    def get_download_url(self, obj):
        request = self.context.get('request')
        from django.urls import reverse
        url = reverse('document-download', args=[obj.pk])
        return request.build_absolute_uri(url) if request else url
