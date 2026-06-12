from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_daemon.tenant_lifecycle import TenantLifecycleRunner


@dataclass
class FakeProc:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class ScriptedRunner:
    def __init__(self, responses: dict[tuple[str, ...], FakeProc]) -> None:
        self._responses = responses
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        proc = self._responses.get(tuple(args), FakeProc(returncode=1, stderr=f"unexpected: {args}"))
        return subprocess.CompletedProcess(
            args=args,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )


def _verify_runner(tenant_slug: str) -> ScriptedRunner:
    hs = f"headscale-{tenant_slug}"
    hp = f"headplane-{tenant_slug}"
    return ScriptedRunner(
        {
            ("docker", "inspect", "-f", "{{.State.Status}}", hs): FakeProc(returncode=0, stdout="running"),
            ("docker", "inspect", "-f", "{{.State.Status}}", hp): FakeProc(returncode=0, stdout="running"),
            ("docker", "exec", "-i", hs, "headscale", "version"): FakeProc(
                returncode=0,
                stdout="headscale version v0.23.0",
            ),
            (
                "docker",
                "inspect",
                "-f",
                "{{if .State.Health}}{{.State.Health.Status}}{{end}}",
                hp,
            ): FakeProc(returncode=0, stdout="healthy"),
        },
    )


class TestTenantLifecycleRunner:
    def test_verify_success(self, tmp_path: Path) -> None:
        runner = TenantLifecycleRunner(
            stack_dir=tmp_path,
            subprocess_runner=_verify_runner("team-1"),
            sleep_fn=lambda _: None,
        )

        result = runner.verify({"tenant_slug": "team-1"})

        assert result.exit_code == 0
        assert result.checks["headscale_container"]["running"] is True
        assert result.checks["headplane_container"]["running"] is True
        assert "0.23.0" in str(result.checks["headscale_version"])
        assert result.checks["headplane_healthy"] is True

    def test_verify_fails_when_headscale_container_missing(self, tmp_path: Path) -> None:
        subprocess_runner = ScriptedRunner(
            {
                (
                    "docker",
                    "inspect",
                    "-f",
                    "{{.State.Status}}",
                    "headscale-team-1",
                ): FakeProc(returncode=1, stderr="No such object"),
            },
        )
        runner = TenantLifecycleRunner(
            stack_dir=tmp_path,
            subprocess_runner=subprocess_runner,
            sleep_fn=lambda _: None,
            container_wait_seconds=0,
            poll_interval_seconds=0,
        )

        result = runner.verify({"tenant_slug": "team-1"})

        assert result.exit_code == 1
        assert result.checks["headscale_container"]["running"] is False

    def test_bootstrap_writes_artifacts_and_refs(self, tmp_path: Path) -> None:
        hs = "headscale-team-1"
        subprocess_runner = ScriptedRunner(
            {
                ("docker", "exec", "-i", hs, "headscale", "apikeys", "create"): FakeProc(
                    returncode=0,
                    stdout="hskey-api-abc123",
                ),
                (
                    "docker",
                    "exec",
                    "-i",
                    hs,
                    "headscale",
                    "users",
                    "create",
                    "admin",
                    "-d",
                    "Admin",
                    "-o",
                    "json",
                ): FakeProc(returncode=0, stdout='{"id":"7","name":"admin"}'),
                (
                    "docker",
                    "exec",
                    "-i",
                    hs,
                    "headscale",
                    "preauthkeys",
                    "create",
                    "--user",
                    "7",
                    "--tags",
                    "tag:gateway",
                    "--reusable",
                    "--expiration",
                    "365d",
                ): FakeProc(returncode=0, stdout="hskey-gateway-abc123"),
                (
                    "docker",
                    "exec",
                    "-i",
                    hs,
                    "headscale",
                    "preauthkeys",
                    "create",
                    "--user",
                    "7",
                    "--tags",
                    "tag:workspace",
                    "--reusable",
                    "--expiration",
                    "365d",
                ): FakeProc(returncode=0, stdout="hskey-workspace-abc123"),
                (
                    "docker",
                    "exec",
                    "-i",
                    hs,
                    "headscale",
                    "policy",
                    "set",
                    "-f",
                    "/etc/headscale/ACL.json",
                ): FakeProc(returncode=0, stdout="policy updated"),
            },
        )
        runner = TenantLifecycleRunner(
            stack_dir=tmp_path,
            subprocess_runner=subprocess_runner,
            sleep_fn=lambda _: None,
        )

        result = runner.bootstrap(
            {
                "tenant_slug": "team-1",
                "output_ref": "worker-output://w1/tenants/team-1/bootstrap",
            },
        )

        assert result.exit_code == 0
        assert result.bootstrap_status == "bootstrapped"
        assert result.bootstrap["api_key"] == "hskey-api-abc123"
        assert result.bootstrap["auth_key_gateway"] == "hskey-gateway-abc123"
        assert result.bootstrap["auth_key_workspace"] == "hskey-workspace-abc123"
        assert result.bootstrap["admin_user_id"] == "7"

        out_file = tmp_path / "results" / "team-1.txt"
        secrets_file = tmp_path / "tenants" / "team-1" / "bootstrap-secrets.env"
        assert out_file.is_file()
        assert secrets_file.is_file()
        assert out_file.stat().st_mode & 0o777 == 0o600
        assert secrets_file.stat().st_mode & 0o777 == 0o600
        secrets_text = secrets_file.read_text(encoding="utf-8")
        assert "API_KEY=hskey-api-abc123" in secrets_text
        assert "AUTH_KEY_GATEWAY=hskey-gateway-abc123" in secrets_text
        assert "AUTH_KEY_WORKSPACE=hskey-workspace-abc123" in secrets_text

    def test_bootstrap_falls_back_to_users_list(self, tmp_path: Path) -> None:
        hs = "headscale-team-1"
        subprocess_runner = ScriptedRunner(
            {
                ("docker", "exec", "-i", hs, "headscale", "apikeys", "create"): FakeProc(
                    returncode=0,
                    stdout="hskey-api-abc123",
                ),
                (
                    "docker",
                    "exec",
                    "-i",
                    hs,
                    "headscale",
                    "users",
                    "create",
                    "admin",
                    "-d",
                    "Admin",
                    "-o",
                    "json",
                ): FakeProc(returncode=1, stderr="user already exists"),
                (
                    "docker",
                    "exec",
                    "-i",
                    hs,
                    "headscale",
                    "users",
                    "list",
                    "-o",
                    "json",
                ): FakeProc(returncode=0, stdout='[{"id":"3","name":"admin"}]'),
                (
                    "docker",
                    "exec",
                    "-i",
                    hs,
                    "headscale",
                    "preauthkeys",
                    "create",
                    "--user",
                    "3",
                    "--tags",
                    "tag:gateway",
                    "--reusable",
                    "--expiration",
                    "365d",
                ): FakeProc(returncode=0, stdout="hskey-gateway-abc123"),
                (
                    "docker",
                    "exec",
                    "-i",
                    hs,
                    "headscale",
                    "preauthkeys",
                    "create",
                    "--user",
                    "3",
                    "--tags",
                    "tag:workspace",
                    "--reusable",
                    "--expiration",
                    "365d",
                ): FakeProc(returncode=0, stdout="hskey-workspace-abc123"),
                (
                    "docker",
                    "exec",
                    "-i",
                    hs,
                    "headscale",
                    "policy",
                    "set",
                    "-f",
                    "/etc/headscale/ACL.json",
                ): FakeProc(returncode=0),
            },
        )
        runner = TenantLifecycleRunner(
            stack_dir=tmp_path,
            subprocess_runner=subprocess_runner,
            sleep_fn=lambda _: None,
        )

        result = runner.bootstrap({"tenant_slug": "team-1"})

        assert result.exit_code == 0
        assert result.bootstrap["admin_user_id"] == "3"
