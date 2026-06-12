from __future__ import annotations

from pathlib import Path

import pytest
from django.test import override_settings

from agents.models import Agent, AgentCommand, AgentType, CommandState
from agents.services import ack_command
from lifecycle.services import enqueue_bootstrap_tenant
from tenants.bootstrap_secrets import (
    read_bootstrap_secrets_env,
    resolve_bootstrap_secrets,
)
from tenants.detail import get_bootstrap_info
from tenants.models import BootstrapStatus, RuntimeStatus, Tenant
from workers.models import Worker, WorkerStatus


@pytest.fixture
def ready_worker(db):
    agent = Agent.objects.create(
        agent_type=AgentType.WORKER,
        token_prefix="agnt_bs1",
        token_hash="d" * 64,
    )
    return Worker.objects.create(
        name="bootstrap-worker",
        hostname="bootstrap.vps.example.com",
        status=WorkerStatus.ONLINE,
        docker_reachable=True,
        agent=agent,
    )


@pytest.fixture
def tenant(ready_worker):
    return Tenant.objects.create(
        slug="detail-team",
        headscale_host="headscale-detail-team.example.com",
        headplane_host="headplane-detail-team.example.com",
        db_name="hs_detail_team",
        worker=ready_worker,
        runtime_status=RuntimeStatus.RUNNING,
        bootstrap_status=BootstrapStatus.PENDING,
    )


@pytest.mark.django_db
class TestBootstrapSecretsFromWorkerFile:
    def test_reads_secrets_env_file(self, tmp_path: Path) -> None:
        secrets_file = tmp_path / "bootstrap-secrets.env"
        secrets_file.write_text(
            "\n".join(
                [
                    "API_KEY=hskey-api-file",
                    "AUTH_KEY_GATEWAY=hskey-gw-file",
                    "AUTH_KEY_WORKSPACE=hskey-ws-file",
                    "ADMIN_USER_ID=99",
                ],
            ),
            encoding="utf-8",
        )

        secrets = read_bootstrap_secrets_env(secrets_file)

        assert secrets == {
            "api_key": "hskey-api-file",
            "auth_key_gateway": "hskey-gw-file",
            "auth_key_workspace": "hskey-ws-file",
            "admin_user_id": "99",
        }

    @override_settings(WORKER_STACK_DIR="/tmp/does-not-exist")
    def test_get_bootstrap_info_backfills_from_legacy_ack_and_secrets_path(
        self,
        tenant,
        ready_worker,
        tmp_path: Path,
    ) -> None:
        secrets_file = tmp_path / "bootstrap-secrets.env"
        secrets_file.write_text(
            "\n".join(
                [
                    "API_KEY=legacy-api-key",
                    "AUTH_KEY_GATEWAY=legacy-gateway-key",
                    "AUTH_KEY_WORKSPACE=legacy-workspace-key",
                    "ADMIN_USER_ID=7",
                ],
            ),
            encoding="utf-8",
        )

        command = enqueue_bootstrap_tenant(tenant)
        stored = AgentCommand.objects.get(id=command.id)
        ack_command(
            stored,
            state=CommandState.ACKED,
            result={
                "exit_code": 0,
                "bootstrap_status": BootstrapStatus.BOOTSTRAPPED,
                "bootstrap": {
                    "admin_user_id": "7",
                    "api_key_ref": "secrets://tenants/detail-team/api_key",
                    "auth_key_gateway_ref": "secrets://tenants/detail-team/gateway",
                    "auth_key_workspace_ref": "secrets://tenants/detail-team/workspace",
                    "secrets_path": str(secrets_file),
                    "output_ref": "worker-output://w1/tenants/detail-team/bootstrap",
                },
            },
        )

        info = get_bootstrap_info(tenant)
        tenant.refresh_from_db()

        assert info is not None
        assert info["api_key"] == "legacy-api-key"
        assert info["auth_key_gateway"] == "legacy-gateway-key"
        assert info["auth_key_workspace"] == "legacy-workspace-key"
        assert tenant.bootstrap_secrets["api_key"] == "legacy-api-key"

    @override_settings(WORKER_STACK_DIR="/tmp/does-not-exist")
    def test_resolve_bootstrap_secrets_uses_stack_dir_fallback(
        self,
        tenant,
        tmp_path: Path,
        settings,
    ) -> None:
        stack_dir = tmp_path / "stack"
        tenant_dir = stack_dir / "tenants" / tenant.slug
        tenant_dir.mkdir(parents=True)
        secrets_file = tenant_dir / "bootstrap-secrets.env"
        secrets_file.write_text("API_KEY=fallback-api\nADMIN_USER_ID=3\n", encoding="utf-8")
        settings.WORKER_STACK_DIR = str(stack_dir)

        secrets = resolve_bootstrap_secrets(tenant, None, persist=True)
        tenant.refresh_from_db()

        assert secrets["api_key"] == "fallback-api"
        assert tenant.bootstrap_secrets["admin_user_id"] == "3"
