from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

import uuid

from accounts.models import AccessLevel, ResourceGrant, ScopeType, User
from accounts.permissions import IsAdmin
from accounts.serializers import GrantSerializer, UserSerializer
from accounts.services.grants import GrantValidationError, create_grant
from core.responses import api_envelope


class AdminUserListCreateView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request: Request) -> Response:
        users = User.objects.all().order_by("username")
        return Response(api_envelope(data=UserSerializer(users, many=True).data))

    def post(self, request: Request) -> Response:
        password = request.data.get("password")
        if not password:
            return Response(
                api_envelope(error="password is required"),
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = UserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = User.objects.create_user(
            password=password,
            **serializer.validated_data,
        )
        return Response(
            api_envelope(data=UserSerializer(user).data),
            status=status.HTTP_201_CREATED,
        )


class AdminUserDetailView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request: Request, user_id: str) -> Response:
        user = get_object_or_404(User, id=user_id)
        return Response(api_envelope(data=UserSerializer(user).data))

    def patch(self, request: Request, user_id: str) -> Response:
        user = get_object_or_404(User, id=user_id)
        serializer = UserSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(api_envelope(data=serializer.data))

    def delete(self, request: Request, user_id: str) -> Response:
        user = get_object_or_404(User, id=user_id)
        user.delete()
        return Response(api_envelope(data=None), status=status.HTTP_200_OK)


class AdminUserGrantListCreateView(APIView):
    permission_classes = [IsAdmin]

    def get(self, request: Request, user_id: str) -> Response:
        user = get_object_or_404(User, id=user_id)
        grants = user.grants.all().order_by("scope_type", "created_at")
        return Response(api_envelope(data=GrantSerializer(grants, many=True).data))

    def post(self, request: Request, user_id: str) -> Response:
        user = get_object_or_404(User, id=user_id)
        scope_type = request.data.get("scope_type")
        scope_id = request.data.get("scope_id")
        access_level = request.data.get("access_level")

        if scope_type not in ScopeType.values:
            return Response(
                api_envelope(error="scope_type is required and must be valid"),
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not scope_id:
            return Response(
                api_envelope(error="scope_id is required"),
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            scope_uuid = uuid.UUID(str(scope_id))
        except ValueError:
            return Response(
                api_envelope(error="scope_id must be a valid UUID"),
                status=status.HTTP_400_BAD_REQUEST,
            )
        if access_level not in AccessLevel.values:
            return Response(
                api_envelope(error="access_level is required and must be valid"),
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            grant = create_grant(
                user=user,
                scope_type=scope_type,
                scope_id=scope_uuid,
                access_level=access_level,
                granted_by=request.user,
            )
        except GrantValidationError as exc:
            return Response(
                api_envelope(error=str(exc)),
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            api_envelope(data=GrantSerializer(grant).data),
            status=status.HTTP_201_CREATED,
        )


class AdminGrantDeleteView(APIView):
    permission_classes = [IsAdmin]

    def delete(self, request: Request, grant_id: str) -> Response:
        grant = get_object_or_404(ResourceGrant, id=grant_id)
        grant.delete()
        return Response(api_envelope(data=None), status=status.HTTP_200_OK)
