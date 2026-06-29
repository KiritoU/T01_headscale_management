from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote

from django.db import transaction
from django.utils import timezone

from agents.models import Agent, AgentCommand, AgentModule, AgentType
from agents.services import create_agent_token, enqueue_command, revoke_agent_credentials
from workers.models import Worker, WorkerEnrollmentToken, WorkerStatus

WORKER_COMMANDS = frozenset(
    {
        "install_module",
        "shutdown",
        "verify_tenant",
        "bootstrap_tenant",
        "provision_tenant",
        "start_tenant",
        "stop_tenant",
        "deprovision_tenant",
    },
)

WORKER_ENROLL_TOKEN_PREFIX = "wrk_"
WORKER_ENROLL_TOKEN_RANDOM_BYTES = 32


@dataclass(frozen=True)
class WorkerEnrollmentCredentials:
    raw_token: str
    worker_id: str
    expires_at: str | None
    install_url: str


def _hash_enroll_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def create_worker_enrollment_token(
    name: str,
    *,
    expires_in_minutes: int = 60,
    max_uses: int = 1,
) -> WorkerEnrollmentCredentials:
    if Worker.objects.filter(name=name).exists():
        msg = f"Worker with name '{name}' already exists"
        raise ValueError(msg)

    expires_at = timezone.now() + timedelta(minutes=expires_in_minutes)
    random_part = secrets.token_urlsafe(WORKER_ENROLL_TOKEN_RANDOM_BYTES)
    raw_token = f"{WORKER_ENROLL_TOKEN_PREFIX}{random_part}"
    prefix = raw_token[:8]
    token_hash = _hash_enroll_token(raw_token)

    worker = Worker.objects.create(name=name, status=WorkerStatus.PENDING)
    WorkerEnrollmentToken.objects.create(
        worker=worker,
        token_hash=token_hash,
        prefix=prefix,
        max_uses=max_uses,
        expires_at=expires_at,
    )

    install_url = f"/worker-agent.sh?token={quote(raw_token, safe='')}"

    return WorkerEnrollmentCredentials(
        raw_token=raw_token,
        worker_id=str(worker.id),
        expires_at=expires_at.isoformat(),
        install_url=install_url,
    )


def revoke_worker_enrollment_token(token: WorkerEnrollmentToken) -> WorkerEnrollmentToken:
    WorkerEnrollmentToken.objects.filter(pk=token.pk).update(revoked=True)
    token.refresh_from_db()
    return token


def _lookup_worker_enrollment_token(raw_token: str) -> WorkerEnrollmentToken | None:
    if not raw_token.startswith(WORKER_ENROLL_TOKEN_PREFIX) or len(raw_token) < 8:
        return None

    prefix = raw_token[:8]
    token_hash = _hash_enroll_token(raw_token)

    try:
        return WorkerEnrollmentToken.objects.select_related("worker").get(
            prefix=prefix,
            token_hash=token_hash,
        )
    except WorkerEnrollmentToken.DoesNotExist:
        return None


def _validate_worker_enrollment_token(token: WorkerEnrollmentToken) -> None:
    if token.revoked:
        msg = "Enrollment token is revoked"
        raise ValueError(msg)
    if token.expires_at and token.expires_at <= timezone.now():
        msg = "Enrollment token is expired"
        raise ValueError(msg)
    if token.uses >= token.max_uses:
        msg = "Enrollment token is exhausted"
        raise ValueError(msg)
    if token.worker.agent_id is not None:
        msg = "Worker is already enrolled"
        raise ValueError(msg)


@transaction.atomic
def register_worker_from_token(
    raw_token: str,
    *,
    hostname: str = "",
) -> tuple[Worker, Agent, str]:
    token = _lookup_worker_enrollment_token(raw_token)
    if token is None:
        msg = "Invalid enrollment token"
        raise ValueError(msg)

    _validate_worker_enrollment_token(token)

    creds = create_agent_token()
    agent = Agent.objects.create(
        agent_type=AgentType.WORKER,
        token_prefix=creds.token_prefix,
        token_hash=creds.token_hash,
    )

    Worker.objects.filter(pk=token.worker_id).update(
        agent=agent,
        hostname=hostname,
        credential_ref=token.prefix,
    )
    WorkerEnrollmentToken.objects.filter(pk=token.pk).update(uses=token.uses + 1)

    token.worker.refresh_from_db()
    return token.worker, agent, creds.raw_token


def enqueue_worker_command(
    worker: Worker,
    command: str,
    payload: dict | None = None,
) -> AgentCommand:
    if worker.agent_id is None:
        msg = "Worker has no enrolled agent"
        raise ValueError(msg)

    if command not in WORKER_COMMANDS:
        msg = f"Unsupported worker command: {command}"
        raise ValueError(msg)

    enqueued = enqueue_command(worker.agent, command=command, payload=payload or {})
    return AgentCommand.objects.get(id=enqueued.id)


def disconnect_worker(worker: Worker) -> Worker:
    """Revoke agent credentials, enqueue shutdown, and mark worker disabled."""
    if worker.agent_id is None:
        msg = "Worker has no enrolled agent"
        raise ValueError(msg)

    revoke_agent_credentials(worker.agent)
    enqueue_command(worker.agent, command="shutdown", payload={})
    Worker.objects.filter(pk=worker.pk).update(
        status=WorkerStatus.DISABLED,
        updated_at=timezone.now(),
    )
    worker.refresh_from_db()
    return worker


@transaction.atomic
def delete_worker(worker: Worker) -> None:
    """Remove worker record after cleaning up agent state; rejects if tenants assigned."""
    if worker.tenants.exists():
        msg = "Cannot delete worker with assigned tenants"
        raise ValueError(msg)

    agent = worker.agent
    if agent is not None:
        AgentCommand.objects.filter(agent=agent).delete()
        AgentModule.objects.filter(agent=agent).delete()
        Worker.objects.filter(pk=worker.pk).update(agent=None)
        agent.delete()

    WorkerEnrollmentToken.objects.filter(worker=worker).delete()
    worker.delete()
