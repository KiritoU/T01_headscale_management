from django.conf import settings
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.responses import api_envelope


class HealthView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request) -> Response:
        return Response(
            api_envelope(
                data={
                    "status": "ok",
                    "service": "headscale-management",
                    "version": settings.APP_VERSION,
                }
            )
        )
