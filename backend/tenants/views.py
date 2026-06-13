from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from accounts.mixins import ScopedQuerysetMixin
from accounts.models import AccessLevel, Role, ScopeType
from accounts.permissions import IsAuthenticatedHuman, ScopedResourceAccess
from accounts.scoping import effective_access
from tenants.models import Tenant
from tenants.serializers import (
    ImportLegacyTenantSerializer,
    TenantDetailSerializer,
    TenantSerializer,
    TenantWriteSerializer,
)


class TenantViewSet(ScopedQuerysetMixin, viewsets.ModelViewSet):
    scope_type = ScopeType.TENANT
    queryset = Tenant.objects.select_related("worker").all()
    permission_classes = [IsAuthenticatedHuman, ScopedResourceAccess]

    def get_scope_id(self, obj: Tenant):
        return obj.id

    def get_serializer_class(self):
        if self.action == "retrieve":
            return TenantDetailSerializer
        if self.action in ("create", "update", "partial_update"):
            return TenantWriteSerializer
        return TenantSerializer

    def get_queryset(self):
        queryset = Tenant.objects.select_related("worker").all()
        if self.action == "retrieve":
            queryset = queryset.prefetch_related("health_checks")

        bootstrap_status = self.request.query_params.get("bootstrap_status")
        if bootstrap_status:
            queryset = queryset.filter(bootstrap_status=bootstrap_status)

        worker_id = self.request.query_params.get("worker")
        if worker_id:
            queryset = queryset.filter(worker_id=worker_id)

        slug_query = self.request.query_params.get("slug")
        if slug_query:
            queryset = queryset.filter(slug__icontains=slug_query)

        return self.filter_by_scope(queryset)

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self._assert_can_create(serializer.validated_data)
        tenant = serializer.save()
        return Response(TenantSerializer(tenant).data, status=201)

    def update(self, request: Request, *args, **kwargs) -> Response:
        partial = kwargs.pop("partial", False)
        tenant = self.get_object()
        serializer = self.get_serializer(tenant, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(TenantSerializer(updated).data)

    @action(detail=False, methods=["post"], url_path="import-legacy")
    def import_legacy(self, request: Request) -> Response:
        serializer = ImportLegacyTenantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self._assert_can_import_legacy(serializer.validated_data)
        tenant = serializer.save()
        return Response(TenantSerializer(tenant).data, status=status.HTTP_201_CREATED)

    def _assert_can_create(self, validated_data: dict) -> None:
        user = self.request.user
        if getattr(user, "is_admin", False):
            return
        if getattr(user, "role", None) != Role.EDITOR:
            raise PermissionDenied("You do not have permission to create tenants.")
        worker = validated_data.get("worker")
        if worker is None:
            raise PermissionDenied("Editors may only create tenants assigned to a granted worker.")
        access = effective_access(user, ScopeType.WORKER, worker.id)
        if access != AccessLevel.EDIT:
            raise PermissionDenied("You do not have edit access to this worker.")

    def _assert_can_import_legacy(self, validated_data: dict) -> None:
        user = self.request.user
        if getattr(user, "is_admin", False):
            return
        if getattr(user, "role", None) != Role.EDITOR:
            raise PermissionDenied("You do not have permission to import tenants.")
        worker_id = validated_data.get("worker_id")
        if worker_id is None:
            raise PermissionDenied("Editors must specify a worker_id they can edit.")
        access = effective_access(user, ScopeType.WORKER, worker_id)
        if access != AccessLevel.EDIT:
            raise PermissionDenied("You do not have edit access to this worker.")
