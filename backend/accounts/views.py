"""Authentication endpoints."""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

from accounts.serializers import EcoTrackTokenObtainPairSerializer, UserSerializer


class LoginView(TokenObtainPairView):
    """
    POST /api/auth/login/

    Body: `{"username": "...", "password": "..."}`
    Returns `access`, `refresh` and the serialised `user`.
    """

    serializer_class = EcoTrackTokenObtainPairSerializer


class MeView(APIView):
    """
    GET /api/auth/me/

    The authenticated user, read from the database rather than from the token's
    claims, so a role change takes effect without re-issuing the token.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserSerializer(request.user).data, status=status.HTTP_200_OK)
