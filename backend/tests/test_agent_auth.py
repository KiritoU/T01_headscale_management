import hashlib
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from agents.authentication import AgentBearerAuthentication
from agents.models import Agent, AgentCommand, AgentType, CommandState
from agents.permissions import IsAgentOwner
from agents.services import (
    AgentTokenCredentials,
    PollResult,
    ack_command,
    create_agent_token,
    dispatch_commands,
    verify_agent_token,
)


@pytest.fixture
def agent_with_token():
    creds = create_agent_token()
    agent = Agent.objects.create(
        agent_type=AgentType.WORKER,
        token_prefix=creds.token_prefix,
        token_hash=creds.token_hash,
        poll_interval_seconds=15,
    )
    return agent, creds.raw_token


@pytest.mark.django_db
class TestCreateAgentToken:
    def test_token_format(self):
        creds = create_agent_token()

        assert creds.raw_token.startswith("agnt_")
        assert len(creds.token_prefix) == 8
        assert creds.token_prefix == creds.raw_token[:8]
        assert len(creds.token_hash) == 64

    def test_token_hash_is_sha256(self):
        creds = create_agent_token()
        expected = hashlib.sha256(creds.raw_token.encode()).hexdigest()

        assert creds.token_hash == expected

    def test_returns_frozen_credentials(self):
        creds = create_agent_token()

        assert isinstance(creds, AgentTokenCredentials)


@pytest.mark.django_db
class TestVerifyAgentToken:
    def test_valid_token_returns_agent(self, agent_with_token):
        agent, raw_token = agent_with_token

        verified = verify_agent_token(raw_token)

        assert verified is not None
        assert verified.agent.id == agent.id

    def test_invalid_token_returns_none(self, agent_with_token):
        assert verify_agent_token("agnt_totally_wrong_token") is None

    def test_wrong_prefix_returns_none(self):
        assert verify_agent_token("agnt_nope") is None


@pytest.mark.django_db
class TestDispatchCommands:
    def test_dispatches_pending_commands(self, agent_with_token):
        agent, _ = agent_with_token
        pending = AgentCommand.objects.create(
            agent=agent,
            command="verify_tenant",
            payload={"tenant_slug": "team-1"},
        )

        result = dispatch_commands(agent)

        assert isinstance(result, PollResult)
        assert len(result.commands) == 1
        assert result.commands[0].id == str(pending.id)
        assert result.commands[0].command == "verify_tenant"

        pending.refresh_from_db()
        assert pending.state == CommandState.DISPATCHED
        assert pending.dispatched_at is not None

    def test_expires_stale_dispatched_commands(self, agent_with_token):
        agent, _ = agent_with_token
        stale_time = timezone.now() - timedelta(seconds=agent.poll_interval_seconds * 2 + 1)
        stale = AgentCommand.objects.create(
            agent=agent,
            command="stale_cmd",
            state=CommandState.DISPATCHED,
            dispatched_at=stale_time,
        )
        fresh = AgentCommand.objects.create(
            agent=agent,
            command="fresh_cmd",
            state=CommandState.PENDING,
        )

        result = dispatch_commands(agent)

        stale.refresh_from_db()
        fresh.refresh_from_db()

        assert stale.state == CommandState.FAILED
        assert fresh.state == CommandState.DISPATCHED
        assert len(result.commands) == 1
        assert result.commands[0].id == str(fresh.id)


@pytest.mark.django_db
class TestAckCommand:
    def test_ack_success(self, agent_with_token):
        agent, _ = agent_with_token
        command = AgentCommand.objects.create(
            agent=agent,
            command="verify_tenant",
            state=CommandState.DISPATCHED,
            dispatched_at=timezone.now(),
        )
        result_payload = {"exit_code": 0, "duration_ms": 100, "logs": "ok"}

        acked = ack_command(command, state=CommandState.ACKED, result=result_payload)

        assert acked.state == CommandState.ACKED
        assert acked.result == result_payload
        assert acked.acked_at is not None

        command.refresh_from_db()
        assert command.state == CommandState.ACKED

    def test_ack_failure(self, agent_with_token):
        agent, _ = agent_with_token
        command = AgentCommand.objects.create(
            agent=agent,
            command="verify_tenant",
            state=CommandState.DISPATCHED,
            dispatched_at=timezone.now(),
        )

        acked = ack_command(
            command,
            state=CommandState.FAILED,
            result={"exit_code": 1, "duration_ms": 50, "logs": "error"},
        )

        assert acked.state == CommandState.FAILED


@pytest.mark.django_db
class TestAgentBearerAuthentication:
    def test_authenticates_valid_bearer_token(self, agent_with_token):
        agent, raw_token = agent_with_token
        factory = APIRequestFactory()
        request = factory.get(
            "/api/v1/agents/test/",
            HTTP_AUTHORIZATION=f"Bearer {raw_token}",
        )
        auth = AgentBearerAuthentication()

        user, token = auth.authenticate(request)

        assert user.id == agent.id
        assert token == raw_token

    def test_rejects_invalid_token(self):
        factory = APIRequestFactory()
        request = factory.get(
            "/api/v1/agents/test/",
            HTTP_AUTHORIZATION="Bearer agnt_invalid",
        )
        auth = AgentBearerAuthentication()

        with pytest.raises(AuthenticationFailed):
            auth.authenticate(request)


@pytest.mark.django_db
class TestIsAgentOwner:
    def test_allows_matching_agent_id(self, agent_with_token):
        agent, _ = agent_with_token
        factory = APIRequestFactory()
        request = factory.get(f"/api/v1/agents/{agent.id}/poll/")
        request.user = agent

        class FakeView:
            kwargs = {"agent_id": str(agent.id)}

        assert IsAgentOwner().has_permission(request, FakeView()) is True

    def test_denies_mismatched_agent_id(self, agent_with_token):
        agent, _ = agent_with_token
        factory = APIRequestFactory()
        request = factory.get(f"/api/v1/agents/{uuid.uuid4()}/poll/")
        request.user = agent

        class FakeView:
            kwargs = {"agent_id": str(uuid.uuid4())}

        assert IsAgentOwner().has_permission(request, FakeView()) is False
