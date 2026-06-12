import os

from django.conf import settings
from rest_framework.permissions import BasePermission, IsAuthenticated


class DebugOrTestAllowAny(BasePermission):
    """Allow unauthenticated access in DEBUG or test runs; require auth otherwise."""

    def has_permission(self, request, view) -> bool:
        if settings.DEBUG or os.environ.get("DJANGO_TEST") == "1":
            return True
        return IsAuthenticated().has_permission(request, view)
