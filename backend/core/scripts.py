import logging
import re
from pathlib import Path

from django.conf import settings
from django.http import HttpRequest, HttpResponse

from core.public_url import get_public_base_url

logger = logging.getLogger(__name__)

_UNAVAILABLE_MESSAGE = "Gateway agent installer script is temporarily unavailable."
_WORKER_UNAVAILABLE_MESSAGE = "Worker agent installer script is temporarily unavailable."

_INJECTED_MARKER = "# __INJECTED_BY_CONTROL_PLANE__"
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+$")


def _inject_script_bootstrap(
    content: str,
    *,
    control_plane_url: str,
    enroll_token: str,
) -> str:
    injection = (
        f"{_INJECTED_MARKER}\n"
        f'CONTROL_PLANE_URL="{control_plane_url}"\n'
        f'ENROLL_TOKEN="{enroll_token}"\n'
    )
    lines = content.splitlines(keepends=True)
    if lines and lines[0].startswith("#!"):
        return lines[0] + injection + "".join(lines[1:])
    return injection + content


def _serve_agent_script(
    request: HttpRequest,
    *,
    script_filename: str,
    unavailable_message: str,
) -> HttpResponse:
    script_path = Path(settings.BASE_DIR) / "scripts" / script_filename
    try:
        content = script_path.read_text(encoding="utf-8")
    except OSError:
        logger.exception("Failed to read %s at %s", script_filename, script_path)
        return HttpResponse(
            unavailable_message,
            status=503,
            content_type="text/plain; charset=utf-8",
        )

    enroll_token = request.GET.get("token", "").strip()
    if enroll_token:
        if not _TOKEN_PATTERN.fullmatch(enroll_token):
            return HttpResponse(
                "Invalid enrollment token format",
                status=400,
                content_type="text/plain; charset=utf-8",
            )
        control_plane_url = get_public_base_url(request)
        if not control_plane_url:
            return HttpResponse(
                "Control plane public URL is not configured",
                status=503,
                content_type="text/plain; charset=utf-8",
            )
        content = _inject_script_bootstrap(
            content,
            control_plane_url=control_plane_url,
            enroll_token=enroll_token,
        )

    response = HttpResponse(content, content_type="text/x-shellscript; charset=utf-8")
    response["Content-Disposition"] = f'inline; filename="{script_filename}"'
    return response


def gateway_agent_script(request: HttpRequest) -> HttpResponse:
    return _serve_agent_script(
        request,
        script_filename="gateway-agent.sh",
        unavailable_message=_UNAVAILABLE_MESSAGE,
    )


def worker_agent_script(request: HttpRequest) -> HttpResponse:
    return _serve_agent_script(
        request,
        script_filename="worker-agent.sh",
        unavailable_message=_WORKER_UNAVAILABLE_MESSAGE,
    )
