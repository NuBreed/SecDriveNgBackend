from rest_framework import serializers

from safety.models import ContactInvite, TrustedContact


class TrustedContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrustedContact
        fields = [
            'id', 'contact_type', 'relationship', 'name', 'phone', 'email',
            'is_primary_emergency', 'is_secondary_emergency',
            'notify_on_journey', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, data):
        ct = data.get('contact_type', getattr(self.instance, 'contact_type', None))
        rel = data.get('relationship', getattr(self.instance, 'relationship', ''))
        if ct == TrustedContact.ContactType.FAMILY and not rel:
            raise serializers.ValidationError(
                {'relationship': 'Relationship is required for family contacts.'}
            )
        return data


# ── New endpoint serializers ───────────────────────────────────────────────────

class PhoneCheckSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=30)


class PhoneCheckResultSerializer(serializers.Serializer):
    is_on_secdrive     = serializers.BooleanField()
    is_on_isafepass    = serializers.BooleanField()
    is_already_trusted = serializers.BooleanField()
    user_id            = serializers.CharField(allow_null=True)


class AddTrustedSerializer(serializers.Serializer):
    phone   = serializers.CharField(max_length=30, required=False, allow_blank=True)
    user_id = serializers.CharField(required=False, allow_blank=True)

    def validate(self, data):
        if not data.get('phone') and not data.get('user_id'):
            raise serializers.ValidationError('Provide phone or user_id.')
        return data


class InviteSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=30)


class ContactInviteSerializer(serializers.ModelSerializer):
    class Meta:
        model  = ContactInvite
        fields = ['id', 'phone', 'status', 'created_at', 'accepted_at']
        read_only_fields = fields
