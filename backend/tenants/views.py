from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from tenants.models import Tenant
from tenants.serializers import (
    ImportLegacyTenantSerializer,
    TenantDetailSerializer,
    TenantSerializer,
    TenantWriteSerializer,
)


class TenantViewSet(viewsets.ModelViewSet):
    queryset = Tenant.objects.select_related("worker").all()

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

        return queryset

    def create(self, request: Request, *args, **kwargs) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
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
        tenant = serializer.save()
        return Response(TenantSerializer(tenant).data, status=status.HTTP_201_CREATED)
