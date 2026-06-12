from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest
import yaml

from agent_daemon.stack_provisioner import StackProvisioner
from lifecycle.generator import generate_tenant_config
from lifecycle.provision_payload import build_provision_payload
from tenants.models import Tenant
from workers.models import Worker


def _completed(args: list[str], *, returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr=stderr)


def _mock_docker_exec(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    joined = " ".join(cmd)
    if "SELECT 1 FROM pg_database" in joined:
        return _completed(cmd, stdout="")
    if "CREATE USER" in joined:
        return _completed(cmd)
    if "CREATE DATABASE" in joined:
        return _completed(cmd)
    if cmd[-2:] == ["restart", "pgbouncer"]:
        return _completed(cmd)
    return _completed(cmd, returncode=1, stderr=f"unexpected docker command: {joined}")


@pytest.fixture
def provision_payload(db) -> dict[str, Any]:
    worker = Worker.objects.create(name="stack-worker", hostname="stack.vps.example.com")
    tenant = Tenant.objects.create(
        slug="team-1",
        headscale_host="headscale-team-1.example.com",
        headplane_host="headplane-team-1.example.com",
        db_name="hs_team_1",
        worker=worker,
        desired_config={"dns": {"magic_dns_base": "tailnet-team-1.example.com"}},
    )
    return build_provision_payload(tenant)


@pytest.mark.django_db
class TestStackProvisioner:
    def test_provision_writes_stack_files(
        self,
        tmp_path,
        provision_payload,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        compose_calls: list[tuple[list[str], Any]] = []

        def mock_compose_runner(args: list[str], cwd, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
            compose_calls.append((args, cwd))
            return _completed(args, stdout="docker compose up -d completed")

        monkeypatch.setattr(
            "agent_daemon.stack_provisioner.subprocess.run",
            _mock_docker_exec,
        )

        provisioner = StackProvisioner(
            stack_dir=tmp_path,
            compose_runner=mock_compose_runner,
        )
        result = provisioner.provision(provision_payload)

        assert result.exit_code == 0
        assert result.runtime_status == "running"
        assert result.config_ref == f"{tmp_path}/tenants/team-1"
        assert compose_calls == [(["up", "-d", "--remove-orphans"], tmp_path)]

        tenant_dir = tmp_path / "tenants" / "team-1"
        assert (tenant_dir / "headscale" / "config.yaml").is_file()
        assert (tenant_dir / "headplane" / "config.yaml").is_file()
        assert (tenant_dir / "compose.snippet.yml").is_file()
        assert (tenant_dir / "metadata.json").is_file()
        assert (tmp_path / "compose.yml").is_file()
        assert (tmp_path / "scripts-root" / "team-1" / "linux.sh").is_file()

        headscale_config = yaml.safe_load((tenant_dir / "headscale" / "config.yaml").read_text())
        assert headscale_config["database"]["postgres"]["pass"]
        assert "pass_ref" not in headscale_config["database"]["postgres"]

        headplane_config = yaml.safe_load((tenant_dir / "headplane" / "config.yaml").read_text())
        assert headplane_config["server"]["cookie_secret"]
        assert headplane_config["auth"]["local_admin"]["password"]
        assert "cookie_secret_ref" not in headplane_config["server"]
        assert "password_ref" not in headplane_config["auth"]["local_admin"]

        compose_yml = (tmp_path / "compose.yml").read_text()
        assert "image: traefik:v3.6.2" in compose_yml
        assert "entrypoints.web.address=:80" in compose_yml
        assert "entrypoints.websecure.address=:443" not in compose_yml
        assert "entrypoints=web" in compose_yml

        state = json.loads((tmp_path / "stack-state.json").read_text(encoding="utf-8"))
        assert state["initialized"] is True
        assert state["production"] is False
        assert state["tenants"] == ["team-1"]
        assert state["databases"]["hs_team_1"] == "host=postgres port=5432 dbname=hs_team_1"

    def test_provision_fails_when_compose_up_fails(
        self,
        tmp_path,
        provision_payload,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def mock_compose_runner(args: list[str], cwd, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
            return _completed(args, returncode=1, stderr="compose failed")

        monkeypatch.setattr(
            "agent_daemon.stack_provisioner.subprocess.run",
            _mock_docker_exec,
        )

        provisioner = StackProvisioner(
            stack_dir=tmp_path,
            compose_runner=mock_compose_runner,
        )
        result = provisioner.provision(provision_payload)

        assert result.exit_code == 1
        assert result.runtime_status == "failed"
        assert "compose failed" in result.logs

    def test_provision_production_requires_acme_env(
        self,
        tmp_path,
        db,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        worker = Worker.objects.create(name="prod-worker", hostname="prod.vps.example.com")
        tenant = Tenant.objects.create(
            slug="prod-1",
            headscale_host="headscale-prod-1.example.com",
            headplane_host="headplane-prod-1.example.com",
            db_name="hs_prod_1",
            worker=worker,
            desired_config={
                "production": True,
                "base_domain": "example.com",
                "download_host": "download.example.com",
                "dns": {"magic_dns_base": "tailnet-prod-1.example.com"},
            },
        )
        payload = build_provision_payload(tenant)

        monkeypatch.setattr(
            "agent_daemon.stack_provisioner.subprocess.run",
            _mock_docker_exec,
        )

        provisioner = StackProvisioner(
            stack_dir=tmp_path,
            compose_runner=lambda args, cwd, timeout: _completed(args),
        )
        result = provisioner.provision(payload)

        assert result.exit_code == 1
        assert "Production mode requires stack .env values" in result.logs

    def test_provision_rejects_mixed_production_modes(
        self,
        tmp_path,
        provision_payload,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (tmp_path / "stack-state.json").write_text(
            '{"initialized": true, "production": true, "tenants": [], "databases": {}}\n',
            encoding="utf-8",
        )

        monkeypatch.setattr(
            "agent_daemon.stack_provisioner.subprocess.run",
            _mock_docker_exec,
        )

        provisioner = StackProvisioner(
            stack_dir=tmp_path,
            compose_runner=lambda args, cwd, timeout: _completed(args),
        )
        result = provisioner.provision(provision_payload)

        assert result.exit_code == 1
        assert "Cannot mix production and dev tenants" in result.logs

    def test_provision_skips_existing_database(
        self,
        tmp_path,
        provision_payload,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def mock_docker_exec(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
            joined = " ".join(cmd)
            if "SELECT 1 FROM pg_database" in joined:
                return _completed(cmd, stdout="1")
            return _mock_docker_exec(cmd, **kwargs)

        monkeypatch.setattr(
            "agent_daemon.stack_provisioner.subprocess.run",
            mock_docker_exec,
        )

        provisioner = StackProvisioner(
            stack_dir=tmp_path,
            compose_runner=lambda args, cwd, timeout: _completed(args),
        )
        result = provisioner.provision(provision_payload)

        assert result.exit_code == 0
        assert "database hs_team_1 already exists" in result.logs

    def test_stop_tenant_runs_compose_stop(self, tmp_path) -> None:
        stack_dir = tmp_path
        (stack_dir / "compose.yml").write_text("services: {}\n", encoding="utf-8")
        compose_calls: list[list[str]] = []

        def mock_compose_runner(args: list[str], cwd, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
            compose_calls.append(args)
            return _completed(args, stdout="stopped")

        provisioner = StackProvisioner(stack_dir=stack_dir, compose_runner=mock_compose_runner)
        result = provisioner.stop_tenant("team-1")

        assert result.exit_code == 0
        assert result.runtime_status == "stopped"
        assert compose_calls == [["stop", "headscale-team-1", "headplane-team-1"]]

    def test_start_tenant_runs_compose_up(self, tmp_path) -> None:
        stack_dir = tmp_path
        (stack_dir / "compose.yml").write_text("services: {}\n", encoding="utf-8")
        compose_calls: list[list[str]] = []

        def mock_compose_runner(args: list[str], cwd, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
            compose_calls.append(args)
            return _completed(args, stdout="started")

        provisioner = StackProvisioner(stack_dir=stack_dir, compose_runner=mock_compose_runner)
        result = provisioner.start_tenant("team-1")

        assert result.exit_code == 0
        assert result.runtime_status == "running"
        assert compose_calls == [["up", "-d", "headscale-team-1", "headplane-team-1"]]
