import re

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from accounts.models import User, Device, AuthEvent


def _unique_username(email):
    base = re.sub(r'[^a-zA-Z0-9_.]', '', (email or '').split('@')[0])[:20] or 'user'
    username = base
    i = 0
    while User.objects.filter(username__iexact=username).exists():
        i += 1
        suffix = str(i)
        username = f'{base[:20 - len(suffix)]}{suffix}'
    return username


class RegisterSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=150)
    last_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=20)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('An account with this email already exists.')
        return value

    def validate_phone(self, value):
        value = value.strip()
        if User.objects.filter(phone=value).exists():
            raise serializers.ValidationError('An account with this phone number already exists.')
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        # New accounts start inactive (Passenger) until OTP verification.
        user = User(
            username=_unique_username(validated_data['email']),
            email=validated_data['email'],
            phone=validated_data['phone'],
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            role=User.Roles.PASSENGER,
            is_active=False,
            is_verified=False,
        )
        user.set_password(validated_data['password'])
        user.save()
        return user


class VerifyOTPSerializer(serializers.Serializer):
    identifier = serializers.CharField(help_text='Email or phone used at registration.')
    code = serializers.CharField()


class ResendOTPSerializer(serializers.Serializer):
    identifier = serializers.CharField()


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(help_text='Email or phone number.')
    password = serializers.CharField(write_only=True)
    # Optional device context
    device_id = serializers.CharField(required=False, allow_blank=True)
    device_type = serializers.CharField(required=False, allow_blank=True)
    platform = serializers.CharField(required=False, allow_blank=True)
    app_version = serializers.CharField(required=False, allow_blank=True)


class ForgotPasswordSerializer(serializers.Serializer):
    identifier = serializers.CharField(help_text='Email or phone number.')


class ResetPasswordSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    code = serializers.CharField()
    new_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value):
        validate_password(value)
        return value


class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_new_password(self, value):
        validate_password(value)
        return value


class GoogleAuthSerializer(serializers.Serializer):
    id_token = serializers.CharField()
    device_id = serializers.CharField(required=False, allow_blank=True)
    device_type = serializers.CharField(required=False, allow_blank=True)
    platform = serializers.CharField(required=False, allow_blank=True)
    app_version = serializers.CharField(required=False, allow_blank=True)


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = [
            'id', 'device_id', 'device_type', 'platform', 'app_version',
            'is_trusted', 'is_active', 'last_login_at', 'created_at',
        ]
        read_only_fields = ['id', 'is_trusted', 'is_active', 'last_login_at', 'created_at']


class AuthEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuthEvent
        fields = [
            'id', 'event_type', 'ip_address', 'user_agent', 'device_id',
            'metadata', 'created_at',
        ]


class UserProfileSerializer(serializers.ModelSerializer):
    isafepass_linked = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'uuid', 'username', 'first_name', 'last_name', 'email',
            'phone', 'role', 'is_verified', 'is_active', 'verification_level',
            'trust_score', 'google_linked', 'isafepass_linked', 'created_at',
        ]
        read_only_fields = [
            'id', 'uuid', 'username', 'email', 'role', 'is_verified',
            'is_active', 'verification_level', 'trust_score',
            'google_linked', 'isafepass_linked', 'created_at',
        ]
