import uuid

import pytest
from django.db import IntegrityError
from django.utils import timezone

from agents.models import Agent, AgentCommand, AgentModule, AgentType, CommandState
from gateways.models import Gateway
from tenants.models import Tenant
from workers.models import Worker


@pytest.fixture
def worker_agent():
    return Agent.objects.create(
        agent_type=AgentType.WORKER,
        token_prefix="agnt_ab",
        token_hash="a" * 64,
    )


@pytest.fixture
def gateway_agent():
    return Agent.objects.create(
        agent_type=AgentType.GATEWAY,
        token_prefix="agnt_cd",
        token_hash="b" * 64,
    )


@pytest.mark.django_db
class TestAgentModel:
    def test_agent_has_uuid_primary_key(self, worker_agent):
        assert isinstance(worker_agent.id, uuid.UUID)

    def test_worker_one_to_one_agent(self, worker_agent):
        worker = Worker.objects.create(name="worker-1", agent=worker_agent)

        assert worker.agent == worker_agent
        assert worker_agent.worker == worker

    def test_gateway_one_to_one_agent(self, gateway_agent):
        tenant = Tenant.objects.create(
            slug="team-1",
            headscale_host="hs.example.com",
            headplane_host="hp.example.com",
            db_name="hs_team_1",
        )
        gateway = Gateway.objects.create(tenant=tenant, hostname="gw-1", agent=gateway_agent)

        assert gateway.agent == gateway_agent
        assert gateway_agent.gateway == gateway


@pytest.mark.django_db
class TestAgentCommandModel:
    def test_command_defaults_to_pending(self, worker_agent):
        command = AgentCommand.objects.create(
            agent=worker_agent,
            command="verify_tenant",
            payload={"tenant_slug": "team-1"},
        )

        assert command.state == CommandState.PENDING
        assert command.dispatched_at is None
        assert command.acked_at is None

    def test_command_state_choices(self, worker_agent):
        for state in (
            CommandState.PENDING,
            CommandState.DISPATCHED,
            CommandState.ACKED,
            CommandState.FAILED,
        ):
            command = AgentCommand.objects.create(
                agent=worker_agent,
                command="noop",
                state=state,
            )
            assert command.state == state


@pytest.mark.django_db
class TestAgentModuleModel:
    def test_module_unique_per_agent(self, worker_agent):
        AgentModule.objects.create(
            agent=worker_agent,
            name="docker",
            installed_at=timezone.now(),
        )

        with pytest.raises(IntegrityError):
            AgentModule.objects.create(
                agent=worker_agent,
                name="docker",
                installed_at=timezone.now(),
            )

    def test_different_agents_can_share_module_name(self, worker_agent, gateway_agent):
        now = timezone.now()
        AgentModule.objects.create(agent=worker_agent, name="core", installed_at=now)
        module = AgentModule.objects.create(agent=gateway_agent, name="core", installed_at=now)

        assert module.name == "core"
