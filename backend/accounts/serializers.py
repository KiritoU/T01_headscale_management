from rest_framework import serializers

from accounts.models import ResourceGrant, User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "is_active",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class GrantSerializer(serializers.ModelSerializer):
    granted_by_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = ResourceGrant
        fields = (
            "id",
            "scope_type",
            "scope_id",
            "access_level",
            "granted_by_id",
            "created_at",
        )
        read_only_fields = fields


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
