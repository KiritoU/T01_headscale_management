import logging
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, HttpResponse

logger = logging.getLogger(__name__)

_UNAVAILABLE_MESSAGE = "Gateway agent installer script is temporarily unavailable."
_WORKER_UNAVAILABLE_MESSAGE = "Worker agent installer script is temporarily unavailable."


def gateway_agent_script(request: HttpRequest) -> HttpResponse:
    script_path = Path(settings.BASE_DIR) / "scripts" / "gateway-agent.sh"
    try:
        content = script_path.read_text(encoding="utf-8")
    except OSError:
        logger.exception("Failed to read gateway-agent.sh at %s", script_path)
        return HttpResponse(
            _UNAVAILABLE_MESSAGE,
            status=503,
            content_type="text/plain; charset=utf-8",
        )

    response = HttpResponse(content, content_type="text/x-shellscript; charset=utf-8")
    response["Content-Disposition"] = 'inline; filename="gateway-agent.sh"'
    return response


def worker_agent_script(request: HttpRequest) -> HttpResponse:
    script_path = Path(settings.BASE_DIR) / "scripts" / "worker-agent.sh"
    try:
        content = script_path.read_text(encoding="utf-8")
    except OSError:
        logger.exception("Failed to read worker-agent.sh at %s", script_path)
        return HttpResponse(
            _WORKER_UNAVAILABLE_MESSAGE,
            status=503,
            content_type="text/plain; charset=utf-8",
        )

    response = HttpResponse(content, content_type="text/x-shellscript; charset=utf-8")
    response["Content-Disposition"] = 'inline; filename="worker-agent.sh"'
    return response
