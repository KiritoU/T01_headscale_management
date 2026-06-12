from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agent_daemon.docker_probe import DOCKER_SOCKET, probe_docker_reachable


class TestProbeDockerReachable:
    def test_returns_false_when_no_socket_and_no_docker_binary(self, tmp_path: Path) -> None:
        fake_socket = tmp_path / "docker.sock"

        with (
            patch("agent_daemon.docker_probe.DOCKER_SOCKET", fake_socket),
            patch("agent_daemon.docker_probe.shutil.which", return_value=None),
        ):
            assert probe_docker_reachable() is False

    def test_returns_true_when_docker_info_succeeds(self) -> None:
        completed = MagicMock(returncode=0)

        with (
            patch("agent_daemon.docker_probe.DOCKER_SOCKET", MagicMock(exists=lambda: True)),
            patch("agent_daemon.docker_probe.subprocess.run", return_value=completed) as run,
        ):
            assert probe_docker_reachable() is True
            run.assert_called_once_with(
                ["docker", "info"],
                capture_output=True,
                timeout=10,
                check=False,
            )

    def test_returns_false_when_docker_info_fails(self) -> None:
        completed = MagicMock(returncode=1)

        with (
            patch("agent_daemon.docker_probe.DOCKER_SOCKET", MagicMock(exists=lambda: True)),
            patch("agent_daemon.docker_probe.subprocess.run", return_value=completed),
        ):
            assert probe_docker_reachable() is False

    def test_returns_false_on_timeout(self) -> None:
        import subprocess

        with (
            patch("agent_daemon.docker_probe.DOCKER_SOCKET", MagicMock(exists=lambda: True)),
            patch(
                "agent_daemon.docker_probe.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd=["docker", "info"], timeout=10),
            ),
        ):
            assert probe_docker_reachable() is False

    def test_returns_false_on_os_error(self) -> None:
        with (
            patch("agent_daemon.docker_probe.DOCKER_SOCKET", MagicMock(exists=lambda: True)),
            patch("agent_daemon.docker_probe.subprocess.run", side_effect=OSError("no docker")),
        ):
            assert probe_docker_reachable() is False

    def test_probes_when_binary_exists_without_socket(self) -> None:
        completed = MagicMock(returncode=0)

        with (
            patch("agent_daemon.docker_probe.DOCKER_SOCKET", MagicMock(exists=lambda: False)),
            patch("agent_daemon.docker_probe.shutil.which", return_value="/usr/bin/docker"),
            patch("agent_daemon.docker_probe.subprocess.run", return_value=completed),
        ):
            assert probe_docker_reachable() is True

    def test_default_socket_path(self) -> None:
        assert DOCKER_SOCKET == Path("/var/run/docker.sock")
