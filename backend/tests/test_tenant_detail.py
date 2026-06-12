from __future__ import annotations

import pytest
from django.utils import timezone

from agents.models import Agent, AgentCommand, AgentType, CommandState
from agents.services import ack_command
from lifecycle.services import enqueue_bootstrap_tenant
from tenants.bootstrap_secrets import extract_bootstrap_secrets
from tenants.detail import (
    HEALTH_CHECK_HISTORY_LIMIT,
    get_bootstrap_info,
    persist_bootstrap_secrets,
    record_health_from_verify,
)
from tenants.models import BootstrapStatus, RuntimeStatus, Tenant, TenantHealth
from workers.models import Worker, WorkerStatus
from workers.tenant_services import (
    maybe_enqueue_bootstrap_after_provision,
    sync_tenant_from_acked_command,
)


@pytest.fixture
def ready_worker(db):
    agent = Agent.objects.create(
        agent_type=AgentType.WORKER,
        token_prefix="agnt_td1",
        token_hash="c" * 64,
    )
    return Worker.objects.create(
        name="detail-worker",
        hostname="detail.vps.example.com",
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
class TestGetBootstrapInfo:
    def test_returns_bootstrap_fields_from_acked_command(self, tenant, ready_worker):
        output_ref = f"worker-output://detail-worker/tenants/{tenant.slug}/bootstrap"
        command = enqueue_bootstrap_tenant(tenant)
        stored = AgentCommand.objects.get(id=command.id)
        ack_command(
            stored,
            state=CommandState.ACKED,
            result={
                "exit_code": 0,
                "bootstrap_status": BootstrapStatus.BOOTSTRAPPED,
                "bootstrap": {
                    "admin_user_id": "admin-42",
                    "api_key": "hskey-api-test",
                    "auth_key_gateway": "hskey-gateway-test",
                    "auth_key_workspace": "hskey-workspace-test",
                    "output_ref": output_ref,
                },
            },
        )
        stored.refresh_from_db()

        info = get_bootstrap_info(tenant)

        assert info is not None
        assert info["command_id"] == str(stored.id)
        assert info["acked_at"] == stored.acked_at.isoformat()
        assert info["admin_user_id"] == "admin-42"
        assert info["api_key"] == "hskey-api-test"
        assert info["auth_key_gateway"] == "hskey-gateway-test"
        assert info["auth_key_workspace"] == "hskey-workspace-test"
        assert info["output_ref"] == output_ref

    def test_returns_secrets_from_persisted_tenant_field(self, tenant, ready_worker):
        Tenant.objects.filter(pk=tenant.pk).update(
            bootstrap_secrets={
                "api_key": "stored-api-key",
                "auth_key_gateway": "stored-gateway-key",
                "auth_key_workspace": "stored-workspace-key",
                "admin_user_id": "admin-stored",
            },
        )
        tenant.refresh_from_db()

        info = get_bootstrap_info(tenant)

        assert info is not None
        assert info["api_key"] == "stored-api-key"
        assert info["auth_key_gateway"] == "stored-gateway-key"
        assert info["auth_key_workspace"] == "stored-workspace-key"
        assert info["admin_user_id"] == "admin-stored"

    def test_returns_none_without_worker_or_bootstrap_artifact(self, db):
        tenant = Tenant.objects.create(
            slug="orphan-team",
            headscale_host="hs.example.com",
            headplane_host="hp.example.com",
            db_name="hs_orphan",
        )

        assert get_bootstrap_info(tenant) is None


@pytest.mark.django_db
class TestBootstrapSecretsPersistence:
    def test_extract_bootstrap_secrets_filters_empty_values(self):
        secrets = extract_bootstrap_secrets(
            {
                "api_key": "  key-1  ",
                "auth_key_gateway": "",
                "auth_key_workspace": None,
                "admin_user_id": "42",
            },
        )

        assert secrets == {"api_key": "key-1", "admin_user_id": "42"}

    def test_sync_persists_bootstrap_secrets_on_ack(self, tenant, ready_worker):
        command = enqueue_bootstrap_tenant(tenant)
        stored = AgentCommand.objects.get(id=command.id)
        ack_command(
            stored,
            state=CommandState.ACKED,
            result={
                "exit_code": 0,
                "bootstrap_status": BootstrapStatus.BOOTSTRAPPED,
                "bootstrap": {
                    "api_key": "synced-api-key",
                    "auth_key_gateway": "synced-gateway-key",
                    "auth_key_workspace": "synced-workspace-key",
                    "admin_user_id": "admin-synced",
                },
            },
        )
        stored.refresh_from_db()

        sync_tenant_from_acked_command(stored)

        tenant.refresh_from_db()
        assert tenant.bootstrap_secrets == {
            "api_key": "synced-api-key",
            "auth_key_gateway": "synced-gateway-key",
            "auth_key_workspace": "synced-workspace-key",
            "admin_user_id": "admin-synced",
        }

    def test_persist_bootstrap_secrets_skips_empty_payload(self, tenant):
        persist_bootstrap_secrets(tenant, None)
        tenant.refresh_from_db()
        assert tenant.bootstrap_secrets == {}


@pytest.mark.django_db
class TestRecordHealthFromVerify:
    def test_creates_health_record_and_trims_to_limit(self, tenant, ready_worker):
        agent = ready_worker.agent
        for index in range(HEALTH_CHECK_HISTORY_LIMIT + 2):
            command = AgentCommand.objects.create(
                agent=agent,
                command="verify_tenant",
                payload={"tenant_id": str(tenant.id), "tenant_slug": tenant.slug},
                state=CommandState.PENDING,
            )
            ack_command(
                command,
                state=CommandState.ACKED,
                result={"exit_code": 0, "duration_ms": 10 + index},
            )
            command.refresh_from_db()
            record_health_from_verify(command, tenant)

        assert TenantHealth.objects.filter(tenant=tenant).count() == HEALTH_CHECK_HISTORY_LIMIT
        latest = TenantHealth.objects.filter(tenant=tenant).order_by("-probed_at").first()
        assert latest is not None
        assert latest.latency_ms == 10 + HEALTH_CHECK_HISTORY_LIMIT + 1

    def test_record_health_is_idempotent_per_command(self, tenant, ready_worker):
        command = AgentCommand.objects.create(
            agent=ready_worker.agent,
            command="verify_tenant",
            payload={"tenant_id": str(tenant.id), "tenant_slug": tenant.slug},
            state=CommandState.PENDING,
        )
        ack_command(
            command,
            state=CommandState.ACKED,
            result={"exit_code": 0, "duration_ms": 33},
        )
        command.refresh_from_db()

        first = record_health_from_verify(command, tenant)
        second = record_health_from_verify(command, tenant)

        assert first is not None
        assert second is not None
        assert first.id == second.id
        assert TenantHealth.objects.filter(tenant=tenant).count() == 1

    def test_records_unhealthy_from_failed_verify(self, tenant, ready_worker):
        command = AgentCommand.objects.create(
            agent=ready_worker.agent,
            command="verify_tenant",
            payload={"tenant_id": str(tenant.id), "tenant_slug": tenant.slug},
            state=CommandState.PENDING,
        )
        ack_command(
            command,
            state=CommandState.FAILED,
            result={"exit_code": 1, "duration_ms": 250, "logs": "headplane unhealthy"},
        )
        command.refresh_from_db()

        health = record_health_from_verify(command, tenant)

        assert health is not None
        assert health.healthy is False
        assert health.latency_ms == 250
        assert health.error_message == "headplane unhealthy"


@pytest.mark.django_db
class TestMaybeEnqueueBootstrapAfterProvision:
    def test_enqueues_bootstrap_after_successful_provision_ack(self, tenant, ready_worker):
        command = AgentCommand.objects.create(
            agent=ready_worker.agent,
            command="provision_tenant",
            payload={"tenant_id": str(tenant.id), "tenant_slug": tenant.slug},
            state=CommandState.PENDING,
        )
        ack_command(
            command,
            state=CommandState.ACKED,
            result={"exit_code": 0, "runtime_status": RuntimeStatus.RUNNING},
        )
        command.refresh_from_db()

        maybe_enqueue_bootstrap_after_provision(command, tenant)

        bootstrap = AgentCommand.objects.filter(
            agent=ready_worker.agent,
            command="bootstrap_tenant",
            payload__tenant_id=str(tenant.id),
        )
        assert bootstrap.count() == 1
        tenant.refresh_from_db()
        assert tenant.bootstrap_status == BootstrapStatus.PROVISIONING

    def test_skips_when_already_bootstrapped(self, tenant, ready_worker):
        Tenant.objects.filter(pk=tenant.pk).update(
            bootstrap_status=BootstrapStatus.BOOTSTRAPPED,
        )
        tenant.refresh_from_db()
        command = AgentCommand.objects.create(
            agent=ready_worker.agent,
            command="provision_tenant",
            payload={"tenant_id": str(tenant.id), "tenant_slug": tenant.slug},
            state=CommandState.PENDING,
        )
        ack_command(
            command,
            state=CommandState.ACKED,
            result={"exit_code": 0, "runtime_status": RuntimeStatus.RUNNING},
        )
        command.refresh_from_db()

        maybe_enqueue_bootstrap_after_provision(command, tenant)

        assert not AgentCommand.objects.filter(command="bootstrap_tenant").exists()


@pytest.mark.django_db
class TestSyncTenantFromAckedCommand:
    def test_records_health_on_verify_ack(self, tenant, ready_worker):
        command = AgentCommand.objects.create(
            agent=ready_worker.agent,
            command="verify_tenant",
            payload={"tenant_id": str(tenant.id), "tenant_slug": tenant.slug},
            state=CommandState.PENDING,
        )
        ack_command(
            command,
            state=CommandState.ACKED,
            result={"exit_code": 0, "duration_ms": 88},
        )
        command.refresh_from_db()

        sync_tenant_from_acked_command(command)

        health = TenantHealth.objects.filter(tenant=tenant).order_by("-probed_at").first()
        assert health is not None
        assert health.healthy is True
        assert health.latency_ms == 88

    def test_auto_enqueues_bootstrap_on_provision_ack(self, tenant, ready_worker):
        command = AgentCommand.objects.create(
            agent=ready_worker.agent,
            command="provision_tenant",
            payload={"tenant_id": str(tenant.id), "tenant_slug": tenant.slug},
            state=CommandState.PENDING,
        )
        ack_command(
            command,
            state=CommandState.ACKED,
            result={"exit_code": 0, "runtime_status": RuntimeStatus.RUNNING},
        )
        command.refresh_from_db()

        sync_tenant_from_acked_command(command)

        assert AgentCommand.objects.filter(
            agent=ready_worker.agent,
            command="bootstrap_tenant",
            payload__tenant_id=str(tenant.id),
        ).exists()
        tenant.refresh_from_db()
        assert tenant.runtime_status == RuntimeStatus.RUNNING
        assert tenant.bootstrap_status == BootstrapStatus.PROVISIONING
