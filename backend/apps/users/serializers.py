import re
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

User = get_user_model()

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['role'] = user.role
        token['username'] = user.username
        token['first_name'] = user.first_name
        token['last_name'] = user.last_name

        if user.role == 'DOCTOR' and hasattr(user, 'doctor_profile'):
            token['profile_id'] = user.doctor_profile.doctor_id
        elif user.role == 'PATIENT' and hasattr(user, 'patient_profile'):
            token['profile_id'] = user.patient_profile.patient_id
            token['uuid_token'] = str(user.patient_profile.uuid_token)

        return token


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'role', 'is_active', 'must_change_password')
        read_only_fields = ('id', 'role', 'is_active', 'must_change_password')


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)

    def validate_new_password(self, value):
        if not any(c.isdigit() for c in value) or not any(c.isalpha() for c in value):
            raise serializers.ValidationError(
                "Password must be at least 8 characters and include letters and numbers."
            )
        try:
            validate_password(value, user=self.context['request'].user)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    def validate(self, attrs):
        user = self.context['request'].user
        if not user.check_password(attrs['old_password']):
            raise serializers.ValidationError({'old_password': 'Current password is incorrect.'})
        if attrs['old_password'] == attrs['new_password']:
            raise serializers.ValidationError({'new_password': 'New password must be different from the current one.'})
        return attrs


class AdminCreateSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        try:
            validate_password(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(list(exc.messages))
        return value

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'password')

    def validate_email(self, value):
        if not value or not str(value).strip():
            raise serializers.ValidationError("Email is required.")
        value = str(value).strip()
        if not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', value):
            raise serializers.ValidationError("Please enter a valid email address.")
        if any(c.isupper() for c in value):
            raise serializers.ValidationError("Email must contain only lowercase letters.")
        return value

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            password=validated_data['password'],
            role=User.Role.ADMIN
        )
        return user


class AdminPasswordResetSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=True)
    new_password = serializers.CharField(required=True, min_length=8)

    def validate_user_id(self, value):
        try:
            user = User.objects.get(pk=value)
            if user.role == User.Role.ADMIN:
                raise serializers.ValidationError("Admins cannot reset other admins passwords through this endpoint.")
            return value
        except User.DoesNotExist:
            raise serializers.ValidationError("User not found.")
