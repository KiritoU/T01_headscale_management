from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.utils import timezone

from agents.models import Agent, AgentCommand, CommandState

TOKEN_PREFIX = "agnt_"
TOKEN_RANDOM_BYTES = 32
REVOKED_TOKEN_HASH = "0" * 64


@dataclass(frozen=True)
class AgentTokenCredentials:
    raw_token: str
    token_prefix: str
    token_hash: str


@dataclass(frozen=True)
class VerifiedAgent:
    agent: Agent


@dataclass(frozen=True)
class DispatchedCommand:
    id: str
    command: str
    payload: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class PollResult:
    commands: tuple[DispatchedCommand, ...]
    expired_count: int


@dataclass(frozen=True)
class EnqueuedCommand:
    id: str | None
    command: str | None
    payload: dict[str, Any]
    state: str | None
    created_at: str | None
    skipped: bool = False
    bootstrap_output_ref: str = ""
    bootstrap_status: str = ""


@dataclass(frozen=True)
class AckedCommand:
    id: str
    state: str
    result: dict[str, Any]
    acked_at: str


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_agent_token() -> AgentTokenCredentials:
    random_part = secrets.token_urlsafe(TOKEN_RANDOM_BYTES)
    raw_token = f"{TOKEN_PREFIX}{random_part}"
    return AgentTokenCredentials(
        raw_token=raw_token,
        token_prefix=raw_token[:8],
        token_hash=_hash_token(raw_token),
    )


def revoke_agent_credentials(agent: Agent) -> Agent:
    """Invalidate agent bearer token so subsequent auth attempts fail."""
    Agent.objects.filter(pk=agent.pk).update(
        token_hash=REVOKED_TOKEN_HASH,
        updated_at=timezone.now(),
    )
    agent.refresh_from_db()
    return agent


def verify_agent_token(raw_token: str) -> VerifiedAgent | None:
    if not raw_token.startswith(TOKEN_PREFIX) or len(raw_token) < 8:
        return None

    prefix = raw_token[:8]
    token_hash = _hash_token(raw_token)

    try:
        agent = Agent.objects.get(token_prefix=prefix, token_hash=token_hash)
    except Agent.DoesNotExist:
        return None

    return VerifiedAgent(agent=agent)


def _expire_stale_dispatched(agent: Agent) -> int:
    cutoff = timezone.now() - timedelta(seconds=agent.poll_interval_seconds * 2)
    stale = AgentCommand.objects.filter(
        agent=agent,
        state=CommandState.DISPATCHED,
        dispatched_at__lt=cutoff,
    )
    return stale.update(state=CommandState.FAILED, updated_at=timezone.now())


def _to_dispatched_command(command: AgentCommand) -> DispatchedCommand:
    return DispatchedCommand(
        id=str(command.id),
        command=command.command,
        payload=dict(command.payload),
        created_at=command.created_at.isoformat(),
    )


def enqueue_command(
    agent: Agent,
    *,
    command: str,
    payload: dict[str, Any] | None = None,
) -> EnqueuedCommand:
    cmd = AgentCommand.objects.create(
        agent=agent,
        command=command,
        payload=payload or {},
    )
    return EnqueuedCommand(
        id=str(cmd.id),
        command=cmd.command,
        payload=dict(cmd.payload),
        state=cmd.state,
        created_at=cmd.created_at.isoformat(),
    )


def dispatch_commands(agent: Agent) -> PollResult:
    expired_count = _expire_stale_dispatched(agent)
    now = timezone.now()

    pending = list(
        AgentCommand.objects.filter(agent=agent, state=CommandState.PENDING).order_by("created_at")
    )

    if pending:
        pending_ids = [cmd.id for cmd in pending]
        AgentCommand.objects.filter(id__in=pending_ids).update(
            state=CommandState.DISPATCHED,
            dispatched_at=now,
            updated_at=now,
        )
        for cmd in pending:
            cmd.state = CommandState.DISPATCHED
            cmd.dispatched_at = now

    commands = tuple(_to_dispatched_command(cmd) for cmd in pending)
    return PollResult(commands=commands, expired_count=expired_count)


def ack_command(
    command: AgentCommand,
    *,
    state: str,
    result: dict[str, Any],
) -> AckedCommand:
    if state not in {CommandState.ACKED, CommandState.FAILED}:
        msg = f"Invalid ack state: {state}"
        raise ValueError(msg)

    now = timezone.now()
    AgentCommand.objects.filter(pk=command.pk).update(
        state=state,
        result=result,
        acked_at=now,
        updated_at=now,
    )

    return AckedCommand(
        id=str(command.id),
        state=state,
        result=dict(result),
        acked_at=now.isoformat(),
    )
