"""Serializers for authentication and the current-user endpoint."""

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Public representation of a user. Role is read-only here."""

    role_display = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "role_display",
            "is_staff",
            "is_superuser",
            "date_joined",
        ]
        read_only_fields = fields


class EcoTrackTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Adds the role as a JWT claim and returns the user alongside the tokens.

    The claim lets the frontend render role-appropriate UI without a second
    request, but the server never trusts it for authorisation - permission
    classes always read the role from the database.
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["username"] = user.get_username()
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data
