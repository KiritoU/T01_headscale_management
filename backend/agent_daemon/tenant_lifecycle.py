from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_daemon.stack_provisioner import DEFAULT_STACK_DIR

DEFAULT_CONTAINER_WAIT_SECONDS = 180
DEFAULT_HEADSCALE_READY_SECONDS = 180
DEFAULT_HEADPLANE_HEALTH_SECONDS = 300
HEADPLANE_HEALTH_URL = "http://127.0.0.1:3000/admin/healthz"
POLL_INTERVAL_SECONDS = 2
HSKEY_PATTERN = re.compile(r"hskey-[a-zA-Z0-9_-]+")

SubprocessRunner = Callable[..., subprocess.CompletedProcess[str]]
SleepFn = Callable[[float], None]


@dataclass(frozen=True)
class VerifyResult:
    exit_code: int
    duration_ms: int
    logs: str
    checks: dict[str, Any]


@dataclass(frozen=True)
class BootstrapResult:
    exit_code: int
    duration_ms: int
    logs: str
    bootstrap: dict[str, Any]
    bootstrap_status: str


def _default_subprocess_runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(*args, **kwargs)


def _default_sleep_fn(seconds: float) -> None:
    time.sleep(seconds)


def _container_names(tenant_slug: str) -> tuple[str, str]:
    return f"headscale-{tenant_slug}", f"headplane-{tenant_slug}"


def _extract_hskey(text: str) -> str | None:
    match = HSKEY_PATTERN.search(text)
    return match.group(0) if match else None


def _parse_user_id(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            payload = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None
    user_id = payload.get("id")
    return str(user_id) if user_id is not None else None


def _parse_admin_user_id_from_list(text: str) -> str | None:
    try:
        users = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(users, list):
        return None
    for user in users:
        if isinstance(user, dict) and user.get("name") == "admin" and user.get("id") is not None:
            return str(user["id"])
    return None


def _chmod_private(path: Path) -> None:
    path.chmod(0o600)


class TenantLifecycleRunner:
    """Verify and bootstrap tenant containers via docker exec."""

    def __init__(
        self,
        stack_dir: Path | None = None,
        *,
        subprocess_runner: SubprocessRunner | None = None,
        sleep_fn: SleepFn | None = None,
        container_wait_seconds: int = DEFAULT_CONTAINER_WAIT_SECONDS,
        headscale_ready_seconds: int = DEFAULT_HEADSCALE_READY_SECONDS,
        headplane_health_seconds: int = DEFAULT_HEADPLANE_HEALTH_SECONDS,
        poll_interval_seconds: float = POLL_INTERVAL_SECONDS,
    ) -> None:
        self._stack_dir = stack_dir or DEFAULT_STACK_DIR
        self._subprocess_runner = subprocess_runner or _default_subprocess_runner
        self._sleep_fn = sleep_fn or _default_sleep_fn
        self._container_wait_seconds = container_wait_seconds
        self._headscale_ready_seconds = headscale_ready_seconds
        self._headplane_health_seconds = headplane_health_seconds
        self._poll_interval_seconds = poll_interval_seconds

    @property
    def stack_dir(self) -> Path:
        return self._stack_dir

    def verify(self, payload: dict[str, Any]) -> VerifyResult:
        started = time.monotonic()
        tenant_slug = str(payload.get("tenant_slug", "unknown"))
        hs_container, hp_container = _container_names(tenant_slug)
        logs: list[str] = [f"verify_tenant: starting checks for {tenant_slug}"]

        checks: dict[str, Any] = {
            "headscale_container": {"name": hs_container, "running": False},
            "headplane_container": {"name": hp_container, "running": False},
            "headscale_version": None,
            "headplane_healthy": False,
        }

        if not self._wait_for_running(hs_container, logs, tenant_slug):
            checks["headscale_container"]["running"] = False
            duration_ms = int((time.monotonic() - started) * 1000)
            message = f"verify_tenant: {hs_container} not running"
            logs.append(message)
            return VerifyResult(exit_code=1, duration_ms=duration_ms, logs="\n".join(logs), checks=checks)

        checks["headscale_container"]["running"] = True

        if not self._wait_for_running(hp_container, logs, tenant_slug):
            checks["headplane_container"]["running"] = False
            duration_ms = int((time.monotonic() - started) * 1000)
            message = f"verify_tenant: {hp_container} not running"
            logs.append(message)
            return VerifyResult(exit_code=1, duration_ms=duration_ms, logs="\n".join(logs), checks=checks)

        checks["headplane_container"]["running"] = True

        version = self._wait_for_headscale_version(hs_container, logs, tenant_slug)
        if version is None:
            duration_ms = int((time.monotonic() - started) * 1000)
            message = f"verify_tenant: headscale not ready in {hs_container}"
            logs.append(message)
            return VerifyResult(exit_code=1, duration_ms=duration_ms, logs="\n".join(logs), checks=checks)

        checks["headscale_version"] = version

        if not self._wait_for_headplane_healthy(hp_container, logs, tenant_slug):
            duration_ms = int((time.monotonic() - started) * 1000)
            message = f"verify_tenant: {hp_container} not healthy"
            logs.append(message)
            return VerifyResult(exit_code=1, duration_ms=duration_ms, logs="\n".join(logs), checks=checks)

        checks["headplane_healthy"] = True
        duration_ms = int((time.monotonic() - started) * 1000)
        logs.append(f"verify_tenant: all checks passed for {tenant_slug}")
        return VerifyResult(exit_code=0, duration_ms=duration_ms, logs="\n".join(logs), checks=checks)

    def bootstrap(self, payload: dict[str, Any]) -> BootstrapResult:
        started = time.monotonic()
        tenant_slug = str(payload.get("tenant_slug", "unknown"))
        output_ref = str(
            payload.get(
                "output_ref",
                f"worker-output://local/tenants/{tenant_slug}/bootstrap",
            ),
        )
        hs_container, _ = _container_names(tenant_slug)
        logs: list[str] = [f"bootstrap_tenant: starting for {tenant_slug}"]

        results_dir = self._stack_dir / "results"
        tenant_dir = self._stack_dir / "tenants" / tenant_slug
        results_dir.mkdir(parents=True, exist_ok=True)
        tenant_dir.mkdir(parents=True, exist_ok=True)

        result_file = results_dir / f"{tenant_slug}.txt"
        secrets_file = tenant_dir / "bootstrap-secrets.env"

        api_key = self._run_headscale(hs_container, ["apikeys", "create"], logs, section="apikeys create")
        if api_key is None:
            duration_ms = int((time.monotonic() - started) * 1000)
            logs.append("bootstrap_tenant: failed to create API key")
            return BootstrapResult(
                exit_code=1,
                duration_ms=duration_ms,
                logs="\n".join(logs),
                bootstrap={"output_ref": output_ref},
                bootstrap_status="failed",
            )

        user_id = self._resolve_admin_user_id(hs_container, logs)
        if user_id is None:
            duration_ms = int((time.monotonic() - started) * 1000)
            logs.append("bootstrap_tenant: failed to resolve admin user id")
            return BootstrapResult(
                exit_code=1,
                duration_ms=duration_ms,
                logs="\n".join(logs),
                bootstrap={"output_ref": output_ref},
                bootstrap_status="failed",
            )

        gateway_key = self._run_headscale(
            hs_container,
            ["preauthkeys", "create", "--user", user_id, "--tags", "tag:gateway", "--reusable", "--expiration", "365d"],
            logs,
            section="preauthkeys create (gateway)",
        )
        workspace_key = self._run_headscale(
            hs_container,
            ["preauthkeys", "create", "--user", user_id, "--tags", "tag:workspace", "--reusable", "--expiration", "365d"],
            logs,
            section="preauthkeys create (workspace)",
        )
        if gateway_key is None or workspace_key is None:
            duration_ms = int((time.monotonic() - started) * 1000)
            logs.append("bootstrap_tenant: failed to create preauth keys")
            return BootstrapResult(
                exit_code=1,
                duration_ms=duration_ms,
                logs="\n".join(logs),
                bootstrap={"output_ref": output_ref},
                bootstrap_status="failed",
            )

        policy_ok = self._run_headscale(
            hs_container,
            ["policy", "set", "-f", "/etc/headscale/ACL.json"],
            logs,
            section="policy set",
            expect_hskey=False,
        )
        if policy_ok is None:
            duration_ms = int((time.monotonic() - started) * 1000)
            logs.append("bootstrap_tenant: failed to set policy")
            return BootstrapResult(
                exit_code=1,
                duration_ms=duration_ms,
                logs="\n".join(logs),
                bootstrap={"output_ref": output_ref},
                bootstrap_status="failed",
            )

        result_file.write_text("\n".join(logs) + "\n", encoding="utf-8")
        _chmod_private(result_file)

        secrets_content = "\n".join(
            [
                f"API_KEY={api_key}",
                f"AUTH_KEY_GATEWAY={gateway_key}",
                f"AUTH_KEY_WORKSPACE={workspace_key}",
                f"ADMIN_USER_ID={user_id}",
                "",
            ],
        )
        secrets_file.write_text(secrets_content, encoding="utf-8")
        _chmod_private(secrets_file)

        duration_ms = int((time.monotonic() - started) * 1000)
        logs.append(f"bootstrap_tenant: completed for {tenant_slug}")
        bootstrap = {
            "api_key": api_key,
            "auth_key_gateway": gateway_key,
            "auth_key_workspace": workspace_key,
            "admin_user_id": user_id,
            "output_ref": output_ref,
        }
        return BootstrapResult(
            exit_code=0,
            duration_ms=duration_ms,
            logs="\n".join(logs),
            bootstrap=bootstrap,
            bootstrap_status="bootstrapped",
        )

    def _run(
        self,
        args: list[str],
        *,
        timeout_seconds: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "check": False,
        }
        if timeout_seconds is not None:
            kwargs["timeout"] = timeout_seconds
        return self._subprocess_runner(args, **kwargs)

    def _docker_inspect_status(self, container: str) -> str:
        proc = self._run(
            ["docker", "inspect", "-f", "{{.State.Status}}", container],
        )
        if proc.returncode != 0:
            return "missing"
        return (proc.stdout or "").strip() or "missing"

    def _docker_inspect_health(self, container: str) -> str:
        proc = self._run(
            ["docker", "inspect", "-f", "{{if .State.Health}}{{.State.Health.Status}}{{end}}", container],
        )
        if proc.returncode != 0:
            return ""
        return (proc.stdout or "").strip()

    def _wait_for_running(self, container: str, logs: list[str], tenant_slug: str) -> bool:
        deadline = time.monotonic() + self._container_wait_seconds
        while time.monotonic() < deadline:
            status = self._docker_inspect_status(container)
            if status == "running":
                logs.append(f"[{tenant_slug}] {container} running")
                return True
            self._sleep_fn(self._poll_interval_seconds)
        logs.append(f"[{tenant_slug}] timeout waiting for {container} running")
        return False

    def _wait_for_headscale_version(
        self,
        container: str,
        logs: list[str],
        tenant_slug: str,
    ) -> str | None:
        deadline = time.monotonic() + self._headscale_ready_seconds
        while time.monotonic() < deadline:
            proc = self._run(["docker", "exec", "-i", container, "headscale", "version"])
            if proc.returncode == 0:
                version = (proc.stdout or proc.stderr or "").strip().splitlines()[0]
                logs.append(f"[{tenant_slug}] headscale ready: {version}")
                return version or "unknown"
            self._sleep_fn(self._poll_interval_seconds)
        logs.append(f"[{tenant_slug}] timeout waiting for headscale ready")
        return None

    def _wait_for_headplane_healthy(
        self,
        container: str,
        logs: list[str],
        tenant_slug: str,
    ) -> bool:
        deadline = time.monotonic() + self._headplane_health_seconds
        while time.monotonic() < deadline:
            health = self._docker_inspect_health(container)
            if health == "healthy":
                logs.append(f"[{tenant_slug}] {container} docker health=healthy")
                return True
            if not health:
                probe = self._run(
                    [
                        "docker",
                        "exec",
                        "-i",
                        container,
                        "sh",
                        "-lc",
                        (
                            f"curl -fsS '{HEADPLANE_HEALTH_URL}' >/dev/null 2>&1 "
                            f"|| wget -qO- '{HEADPLANE_HEALTH_URL}' >/dev/null 2>&1"
                        ),
                    ],
                )
                if probe.returncode == 0:
                    logs.append(f"[{tenant_slug}] {container} HTTP health probe OK")
                    return True
            self._sleep_fn(self._poll_interval_seconds)
        logs.append(f"[{tenant_slug}] timeout waiting for {container} healthy")
        return False

    def _docker_exec_headscale(
        self,
        container: str,
        headscale_args: list[str],
    ) -> subprocess.CompletedProcess[str]:
        return self._run(["docker", "exec", "-i", container, "headscale", *headscale_args])

    def _run_headscale(
        self,
        container: str,
        headscale_args: list[str],
        logs: list[str],
        *,
        section: str,
        expect_hskey: bool = True,
    ) -> str | None:
        logs.append(f"## {section}")
        proc = self._docker_exec_headscale(container, headscale_args)
        output = "\n".join(part for part in [proc.stdout, proc.stderr] if part).strip()
        if output:
            logs.append(output)
        if proc.returncode != 0:
            logs.append(f"[ERR] {section} failed")
            return None
        if expect_hskey:
            key = _extract_hskey(output)
            if key is None:
                logs.append(f"[ERR] {section} missing hskey output")
                return None
            return key
        return output or "ok"

    def _resolve_admin_user_id(self, container: str, logs: list[str]) -> str | None:
        logs.append("## users create admin -d Admin -o json")
        create_proc = self._docker_exec_headscale(
            container,
            ["users", "create", "admin", "-d", "Admin", "-o", "json"],
        )
        create_output = "\n".join(
            part for part in [create_proc.stdout, create_proc.stderr] if part
        ).strip()
        if create_output:
            logs.append(create_output)

        user_id = _parse_user_id(create_output)
        if user_id is not None:
            logs.append(f"parsed_user_id: {user_id}")
            return user_id

        logs.append("WARN: users create failed; trying users list")
        list_proc = self._docker_exec_headscale(container, ["users", "list", "-o", "json"])
        list_output = (list_proc.stdout or "").strip()
        if list_output:
            logs.append(list_output)
        user_id = _parse_admin_user_id_from_list(list_output)
        if user_id is not None:
            logs.append(f"parsed_user_id: {user_id}")
            return user_id

        logs.append("[ERR] could not resolve admin user id")
        return None
