from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable
from typing import Any

ModuleRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]

NMAP_MODULE = "nmap"
MASSCAN_MODULE = "masscan"
TAILSCALE_MODULE = "tailscale"
VULN_NSE_PACK_MODULE = "vuln-nse-pack"
IOT_PROBES_MODULE = "iot-probes"
NUCLEI_MODULE = "nuclei"

SUPPORTED_MODULES = frozenset(
    {
        NMAP_MODULE,
        MASSCAN_MODULE,
        TAILSCALE_MODULE,
        VULN_NSE_PACK_MODULE,
        IOT_PROBES_MODULE,
        NUCLEI_MODULE,
    },
)

INSTALL_TIMEOUT_SECONDS = 300
NMAP_APT_COMMAND = ["apt-get", "install", "-y", "nmap"]
MASSCAN_APT_COMMAND = ["apt-get", "install", "-y", "masscan"]
TAILSCALE_INSTALL_SCRIPT = "curl -fsSL https://tailscale.com/install.sh | sh"
HSM_BASE_DIR = "/opt/hsm"
NUCLEI_INSTALL_DIR = "/opt/hsm/bin"
NUCLEI_BINARY = f"{NUCLEI_INSTALL_DIR}/nuclei"


def _nuclei_installed() -> bool:
    return shutil.which("nuclei") is not None or os.path.isfile(NUCLEI_BINARY)


def install_gateway_module(
    module_name: str,
    *,
    command_runner: ModuleRunner | None = None,
    control_plane_url: str | None = None,
) -> tuple[dict[str, Any], str]:
    runner = command_runner or _default_runner

    if module_name == NMAP_MODULE:
        return _ensure_binary(
            binary="nmap",
            install_command=["sh", "-c", " ".join(NMAP_APT_COMMAND)],
            runner=runner,
            module_name=module_name,
        )
    if module_name == MASSCAN_MODULE:
        return _ensure_binary(
            binary="masscan",
            install_command=["sh", "-c", " ".join(MASSCAN_APT_COMMAND)],
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
    if module_name == VULN_NSE_PACK_MODULE:
        return _install_bundle(
            module_name=module_name,
            bundle_name="gateway-vuln-nse-pack.tar.gz",
            target_dir=f"{HSM_BASE_DIR}/nse",
            control_plane_url=control_plane_url,
            runner=runner,
        )
    if module_name == IOT_PROBES_MODULE:
        return _install_bundle(
            module_name=module_name,
            bundle_name="gateway-iot-probes.tar.gz",
            target_dir=f"{HSM_BASE_DIR}/iot-probes",
            control_plane_url=control_plane_url,
            runner=runner,
        )
    if module_name == NUCLEI_MODULE:
        return _install_nuclei(runner=runner)

    return (
        {
            "exit_code": 1,
            "duration_ms": 0,
            "logs": f"unsupported module: {module_name}",
        },
        "failed",
    )


def _install_bundle(
    *,
    module_name: str,
    bundle_name: str,
    target_dir: str,
    control_plane_url: str | None,
    runner: ModuleRunner,
) -> tuple[dict[str, Any], str]:
    base_url = control_plane_url or os.environ.get("CONTROL_PLANE_URL", "")
    if not base_url:
        return (
            {
                "exit_code": 1,
                "duration_ms": 0,
                "logs": "CONTROL_PLANE_URL is required for bundle install",
            },
            "failed",
        )

    marker = os.path.join(target_dir, ".installed")
    if os.path.isfile(marker):
        return (
            {
                "exit_code": 0,
                "duration_ms": 1,
                "logs": f"{module_name} already installed",
            },
            "acked",
        )

    started = time.monotonic()
    install_script = (
        f"mkdir -p {target_dir} && "
        f"curl -fsSL {base_url.rstrip('/')}/{bundle_name} | tar -xzf - -C {target_dir} && "
        f"touch {marker}"
    )
    try:
        proc = runner(["sh", "-c", install_script])
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

    return (
        {
            "exit_code": 0,
            "duration_ms": duration_ms,
            "logs": f"installed module: {module_name}",
        },
        "acked",
    )


def _install_nuclei(*, runner: ModuleRunner) -> tuple[dict[str, Any], str]:
    if _nuclei_installed():
        return (
            {
                "exit_code": 0,
                "duration_ms": 1,
                "logs": "nuclei already installed",
            },
            "acked",
        )

    started = time.monotonic()
    install_script = (
        f"mkdir -p {NUCLEI_INSTALL_DIR} && "
        "curl -fsSL https://github.com/projectdiscovery/nuclei/releases/download/v3.9.0/nuclei_3.9.0_linux_amd64.zip "
        f"-o /tmp/nuclei.zip && unzip -o /tmp/nuclei.zip -d {NUCLEI_INSTALL_DIR} && "
        f"chmod +x {NUCLEI_INSTALL_DIR}/nuclei && "
        f"{NUCLEI_INSTALL_DIR}/nuclei -update-templates -silent -no-stdin"
    )
    try:
        proc = runner(["sh", "-c", install_script])
    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - started) * 1000)
        return (
            {
                "exit_code": 1,
                "duration_ms": duration_ms,
                "logs": "nuclei install timed out",
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
    if proc.returncode != 0 or not _nuclei_installed():
        logs = (proc.stderr or proc.stdout or "nuclei install failed").strip()
        return (
            {
                "exit_code": proc.returncode or 1,
                "duration_ms": duration_ms,
                "logs": logs,
            },
            "failed",
        )

    return (
        {
            "exit_code": 0,
            "duration_ms": duration_ms,
            "logs": "installed module: nuclei",
        },
        "acked",
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
