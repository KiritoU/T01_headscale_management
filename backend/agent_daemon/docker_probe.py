"""Docker availability probe for worker agent heartbeats.

Probed on every heartbeat (not only at enroll) so a transient daemon outage
does not leave a stale false negative on the control plane. Docker install is
handled separately via install_module to keep enrollment fast.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

DOCKER_SOCKET = Path("/var/run/docker.sock")
DOCKER_PROBE_TIMEOUT_SECONDS = 10


def probe_docker_reachable() -> bool:
    """Return True when the Docker daemon responds to `docker info`."""
    if not DOCKER_SOCKET.exists() and shutil.which("docker") is None:
        return False

    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=DOCKER_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False

    return result.returncode == 0
