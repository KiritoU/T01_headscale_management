from __future__ import annotations

import shutil
import subprocess
import time
from collections.abc import Callable
from typing import Any

ModuleRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]

NMAP_MODULE = "nmap"
TAILSCALE_MODULE = "tailscale"
INSTALL_TIMEOUT_SECONDS = 300

NMAP_APT_COMMAND = ["apt-get", "install", "-y", "nmap"]
TAILSCALE_INSTALL_SCRIPT = "curl -fsSL https://tailscale.com/install.sh | sh"


def install_gateway_module(
    module_name: str,
    *,
    command_runner: ModuleRunner | None = None,
) -> tuple[dict[str, Any], str]:
    runner = command_runner or _default_runner

    if module_name == NMAP_MODULE:
        return _ensure_binary(
            binary="nmap",
            install_command=["sh", "-c", " ".join(NMAP_APT_COMMAND)],
            runner=runner,
            module_name=module_name,
        )
    if module_name == TAILSCALE_MODULE:
        return _ensure_binary(
            binary="tailscale",
            install_command=["sh", "-c", TAILSCALE_INSTALL_SCRIPT],
            runner=runner,
            module_name=module_name,
        )

    return (
        {
            "exit_code": 1,
            "duration_ms": 0,
            "logs": f"unsupported module: {module_name}",
        },
        "failed",
    )


def _ensure_binary(
    *,
    binary: str,
    install_command: list[str],
    runner: ModuleRunner,
    module_name: str,
) -> tuple[dict[str, Any], str]:
    if shutil.which(binary):
        return (
            {
                "exit_code": 0,
                "duration_ms": 1,
                "logs": f"{module_name} already installed ({binary} present)",
            },
            "acked",
        )

    started = time.monotonic()
    try:
        proc = runner(install_command)
    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - started) * 1000)
        return (
            {
                "exit_code": 1,
                "duration_ms": duration_ms,
                "logs": f"{module_name} install timed out",
            },
            "failed",
        )
    except OSError as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        return (
            {
                "exit_code": 1,
                "duration_ms": duration_ms,
                "logs": str(exc),
            },
            "failed",
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    if proc.returncode != 0:
        logs = (proc.stderr or proc.stdout or f"{module_name} install failed").strip()
        return (
            {
                "exit_code": proc.returncode,
                "duration_ms": duration_ms,
                "logs": logs,
            },
            "failed",
        )

    if not shutil.which(binary):
        return (
            {
                "exit_code": 1,
                "duration_ms": duration_ms,
                "logs": f"{module_name} install finished but {binary} not found in PATH",
            },
            "failed",
        )

    return (
        {
            "exit_code": 0,
            "duration_ms": duration_ms,
            "logs": f"installed module: {module_name}",
        },
        "acked",
    )


def _default_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=INSTALL_TIMEOUT_SECONDS,
        check=False,
    )
