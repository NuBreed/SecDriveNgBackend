from rest_framework import serializers

from safety.models import TrustedContact


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
