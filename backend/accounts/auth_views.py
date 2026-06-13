from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from accounts.permissions import IsAuthenticatedHuman
from accounts.serializers import (
    GrantSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    UserSerializer,
)
from core.responses import api_envelope

INVALID_CREDENTIALS_MESSAGE = "Invalid username or password."


@method_decorator(ensure_csrf_cookie, name="dispatch")
class CsrfView(APIView):
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        return Response(api_envelope(data={"csrf_token": get_token(request)}))


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data["username"]
        password = serializer.validated_data["password"]
        user = authenticate(request, username=username, password=password)

        if user is None or not user.is_active:
            return Response(
                api_envelope(error=INVALID_CREDENTIALS_MESSAGE),
                status=status.HTTP_401_UNAUTHORIZED,
            )

        login(request, user)
        return Response(api_envelope(data=UserSerializer(user).data))


class LogoutView(APIView):
    permission_classes = [IsAuthenticatedHuman]

    def post(self, request: Request) -> Response:
        logout(request)
        return Response(api_envelope(data=None))


class MeView(APIView):
    permission_classes = [IsAuthenticatedHuman]

    def get(self, request: Request) -> Response:
        user = request.user
        grants = user.grants.all().order_by("scope_type", "created_at")
        return Response(
            api_envelope(
                data={
                    "user": UserSerializer(user).data,
                    "grants": GrantSerializer(grants, many=True).data,
                },
            ),
        )


class PasswordChangeView(APIView):
    permission_classes = [IsAuthenticatedHuman]

    def post(self, request: Request) -> Response:
        serializer = PasswordChangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = request.user
        current_password = serializer.validated_data["current_password"]
        new_password = serializer.validated_data["new_password"]

        if not user.check_password(current_password):
            return Response(
                api_envelope(error="Current password is incorrect."),
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.set_password(new_password)
        user.save(update_fields=["password"])
        update_session_auth_hash(request, user)
        return Response(api_envelope(data=UserSerializer(user).data))
