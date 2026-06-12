from __future__ import annotations

import json
import secrets
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from lifecycle.identifiers import escape_sql_literal, validate_db_name
from lifecycle.render import (
    dict_to_yaml,
    resolve_headplane_config_for_worker,
    resolve_headscale_config_for_worker,
)
from lifecycle.stack_generator import (
    pgbouncer_database_line,
    stack_file_bundle,
)

DEFAULT_STACK_DIR = Path("/opt/headscale-worker-stack")
DEFAULT_POSTGRES_USER = "headscale"
DEFAULT_PGBOUNCER_USER = "pgbouncer"
COMPOSE_TIMEOUT_SECONDS = 600


class StackProvisionError(Exception):
    """Raised when stack provisioning cannot complete."""


@dataclass(frozen=True)
class ProvisionResult:
    exit_code: int
    duration_ms: int
    logs: str
    runtime_status: str
    config_ref: str


@dataclass(frozen=True)
class TenantRuntimeResult:
    exit_code: int
    duration_ms: int
    logs: str
    runtime_status: str


def tenant_compose_services(tenant_slug: str) -> tuple[str, str]:
    return f"headscale-{tenant_slug}", f"headplane-{tenant_slug}"


ComposeRunner = Callable[[list[str], Path, int], subprocess.CompletedProcess[str]]


def _default_compose_runner(
    args: list[str],
    cwd: Path,
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    lines = [f"{key}={value}" for key, value in sorted(values.items())]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ensure_secret(values: dict[str, str], key: str) -> str:
    existing = values.get(key, "").strip()
    if existing and not existing.startswith("change-me"):
        return existing
    generated = secrets.token_hex(16)
    values[key] = generated
    return generated


class StackProvisioner:
    def __init__(
        self,
        stack_dir: Path | None = None,
        *,
        compose_runner: ComposeRunner | None = None,
        compose_timeout_seconds: int = COMPOSE_TIMEOUT_SECONDS,
    ) -> None:
        self._stack_dir = stack_dir or DEFAULT_STACK_DIR
        self._compose_runner = compose_runner or _default_compose_runner
        self._compose_timeout_seconds = compose_timeout_seconds

    @property
    def stack_dir(self) -> Path:
        return self._stack_dir

    def provision(self, payload: dict[str, Any]) -> ProvisionResult:
        started = time.monotonic()
        tenant_slug = str(payload.get("tenant_slug", "unknown"))
        config_ref = f"{self._stack_dir}/tenants/{tenant_slug}"

        try:
            logs = self._provision_impl(payload)
            duration_ms = int((time.monotonic() - started) * 1000)
            return ProvisionResult(
                exit_code=0,
                duration_ms=duration_ms,
                logs=logs,
                runtime_status="running",
                config_ref=config_ref,
            )
        except StackProvisionError as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return ProvisionResult(
                exit_code=1,
                duration_ms=duration_ms,
                logs=str(exc),
                runtime_status="failed",
                config_ref=config_ref,
            )

    def _provision_impl(self, payload: dict[str, Any]) -> str:
        tenant_slug = str(payload["tenant_slug"])
        production = bool(payload.get("production"))
        db_name = str(payload["db_name"])
        validate_db_name(db_name)

        if production:
            env_values = _read_env_file(self._stack_dir / ".env")
            missing = [
                key
                for key in ("ACME_EMAIL", "CF_DNS_API_TOKEN")
                if not env_values.get(key) or env_values[key].startswith("replace-me")
            ]
            if missing:
                msg = (
                    "Production mode requires stack .env values: "
                    + ", ".join(missing)
                )
                raise StackProvisionError(msg)

        self._stack_dir.mkdir(parents=True, exist_ok=True)
        (self._stack_dir / "traefik" / "acme").mkdir(parents=True, exist_ok=True)
        (self._stack_dir / "postgres" / "init").mkdir(parents=True, exist_ok=True)
        (self._stack_dir / "pgbouncer").mkdir(parents=True, exist_ok=True)
        (self._stack_dir / "scripts-root" / tenant_slug).mkdir(parents=True, exist_ok=True)

        state = self._load_state()
        download_host = str(state.get("download_host") or payload["download_host"])
        if state.get("initialized") and state.get("production") != production:
            raise StackProvisionError(
                "Cannot mix production and dev tenants on one worker stack. "
                "Use a separate worker or recreate the stack directory.",
            )

        env_path = self._stack_dir / ".env"
        env_values = _read_env_file(env_path)
        postgres_password = _ensure_secret(env_values, "POSTGRES_PASSWORD")
        pgbouncer_password = _ensure_secret(env_values, "PGBOUNCER_PASSWORD")
        env_values.setdefault("PGBOUNCER_USER", DEFAULT_PGBOUNCER_USER)
        env_values.setdefault("POSTGRES_APP_USER", DEFAULT_POSTGRES_USER)
        if production:
            env_values.setdefault("ACME_EMAIL", "admin@example.com")
            env_values.setdefault("CF_DNS_API_TOKEN", "replace-me")
        _write_env_file(env_path, env_values)
        env_path.chmod(0o600)

        tenant_dir = self._stack_dir / "tenants" / tenant_slug
        tenant_dir.mkdir(parents=True, exist_ok=True)
        (tenant_dir / "headscale").mkdir(parents=True, exist_ok=True)
        (tenant_dir / "headplane").mkdir(parents=True, exist_ok=True)
        (tenant_dir / "headscale" / "data").mkdir(parents=True, exist_ok=True)
        (tenant_dir / "headplane" / "data").mkdir(parents=True, exist_ok=True)

        tenant_secrets_path = tenant_dir / "secrets.env"
        tenant_secrets = _read_env_file(tenant_secrets_path)
        cookie_secret = _ensure_secret(tenant_secrets, "HEADPLANE_COOKIE_SECRET")
        admin_password = _ensure_secret(tenant_secrets, "HEADPLANE_ADMIN_PASSWORD")
        _write_env_file(tenant_secrets_path, tenant_secrets)
        tenant_secrets_path.chmod(0o600)

        headscale_config = resolve_headscale_config_for_worker(
            dict(payload["headscale_config"]),
            postgres_password=postgres_password,
        )
        headplane_config = resolve_headplane_config_for_worker(
            dict(payload["headplane_config"]),
            cookie_secret=cookie_secret,
            admin_password=admin_password,
        )

        headscale_config_path = tenant_dir / "headscale" / "config.yaml"
        headscale_config_path.write_text(
            dict_to_yaml(headscale_config),
            encoding="utf-8",
        )
        headscale_config_path.chmod(0o600)
        headplane_config_path = tenant_dir / "headplane" / "config.yaml"
        headplane_config_path.write_text(
            dict_to_yaml(headplane_config),
            encoding="utf-8",
        )
        headplane_config_path.chmod(0o600)
        (tenant_dir / "headscale" / "dns_records.json").write_text(
            str(payload.get("dns_records_json", "[]\n")),
            encoding="utf-8",
        )
        (tenant_dir / "compose.snippet.yml").write_text(
            str(payload["compose_snippet"]),
            encoding="utf-8",
        )
        (tenant_dir / "metadata.json").write_text(
            json.dumps(
                {
                    "slug": tenant_slug,
                    "db_name": db_name,
                    "production": production,
                    "download_host": download_host,
                    "login_server": payload.get("login_server"),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        client_scripts = dict(payload.get("client_scripts") or {})
        scripts_dir = self._stack_dir / "scripts-root" / tenant_slug
        for name, content in client_scripts.items():
            script_path = scripts_dir / name
            script_path.write_text(str(content), encoding="utf-8")
            script_path.chmod(0o755)

        tenants = set(state.get("tenants", []))
        tenants.add(tenant_slug)
        databases = dict(state.get("databases", {}))
        databases[db_name] = pgbouncer_database_line(db_name)

        tenant_blocks = self._collect_tenant_compose_blocks(sorted(tenants))
        bundle = stack_file_bundle(
            production=production,
            download_host=download_host,
            database_lines=databases,
            postgres_user=DEFAULT_POSTGRES_USER,
            postgres_password=postgres_password,
            pgbouncer_user=env_values.get("PGBOUNCER_USER", DEFAULT_PGBOUNCER_USER),
            pgbouncer_password=pgbouncer_password,
            database_names_for_init=sorted(databases),
            tenant_service_blocks=tenant_blocks,
        )
        for relative_path, content in bundle.items():
            target = self._stack_dir / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        compose_logs = self._compose_up()
        db_logs = self._ensure_database(db_name, postgres_password)

        state.update(
            {
                "initialized": True,
                "production": production,
                "download_host": download_host,
                "tenants": sorted(tenants),
                "databases": databases,
            },
        )
        self._save_state(state)

        return "\n".join(
            part
            for part in (
                f"provision_tenant: wrote stack for {tenant_slug}",
                compose_logs,
                db_logs,
            )
            if part
        )

    def _load_state(self) -> dict[str, Any]:
        state_path = self._stack_dir / "stack-state.json"
        if not state_path.is_file():
            return {}
        return json.loads(state_path.read_text(encoding="utf-8"))

    def _save_state(self, state: dict[str, Any]) -> None:
        state_path = self._stack_dir / "stack-state.json"
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def _collect_tenant_compose_blocks(self, tenant_slugs: list[str]) -> list[str]:
        blocks: list[str] = []
        for slug in tenant_slugs:
            snippet_path = self._stack_dir / "tenants" / slug / "compose.snippet.yml"
            if snippet_path.is_file():
                blocks.append(snippet_path.read_text(encoding="utf-8"))
        return blocks

    def start_tenant(self, tenant_slug: str) -> TenantRuntimeResult:
        return self._run_tenant_compose_action(
            tenant_slug,
            compose_args=["up", "-d", *tenant_compose_services(tenant_slug)],
            success_status="running",
            action_label="start_tenant",
        )

    def stop_tenant(self, tenant_slug: str) -> TenantRuntimeResult:
        return self._run_tenant_compose_action(
            tenant_slug,
            compose_args=["stop", *tenant_compose_services(tenant_slug)],
            success_status="stopped",
            action_label="stop_tenant",
        )

    def _run_tenant_compose_action(
        self,
        tenant_slug: str,
        *,
        compose_args: list[str],
        success_status: str,
        action_label: str,
    ) -> TenantRuntimeResult:
        started = time.monotonic()
        compose_path = self._stack_dir / "compose.yml"
        if not compose_path.is_file():
            duration_ms = int((time.monotonic() - started) * 1000)
            return TenantRuntimeResult(
                exit_code=1,
                duration_ms=duration_ms,
                logs=f"{action_label}: stack compose.yml not found at {compose_path}",
                runtime_status="failed",
            )

        proc = self._compose_runner(
            compose_args,
            self._stack_dir,
            self._compose_timeout_seconds,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        output = "\n".join(part for part in (proc.stdout, proc.stderr) if part).strip()
        if proc.returncode != 0:
            return TenantRuntimeResult(
                exit_code=proc.returncode,
                duration_ms=duration_ms,
                logs=output or f"{action_label}: docker compose failed",
                runtime_status="failed",
            )

        hs, hp = tenant_compose_services(tenant_slug)
        logs = output or f"{action_label}: {hs} and {hp} updated"
        return TenantRuntimeResult(
            exit_code=0,
            duration_ms=duration_ms,
            logs=logs,
            runtime_status=success_status,
        )

    def _compose_up(self) -> str:
        proc = self._compose_runner(
            ["up", "-d", "--remove-orphans"],
            self._stack_dir,
            self._compose_timeout_seconds,
        )
        output = "\n".join(part for part in (proc.stdout, proc.stderr) if part).strip()
        if proc.returncode != 0:
            raise StackProvisionError(output or "docker compose up failed")
        return output or "docker compose up -d completed"

    def _ensure_database(self, db_name: str, postgres_password: str) -> str:
        escaped_password = escape_sql_literal(postgres_password)
        check = subprocess.run(
            [
                "docker",
                "exec",
                "postgres",
                "psql",
                "-U",
                "postgres",
                "-tAc",
                f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if check.returncode != 0:
            raise StackProvisionError(
                check.stderr or check.stdout or "database existence check failed",
            )

        if check.stdout.strip() == "1":
            return f"database {db_name} already exists"

        create = subprocess.run(
            [
                "docker",
                "exec",
                "postgres",
                "psql",
                "-U",
                "postgres",
                "-c",
                (
                    f"CREATE USER {DEFAULT_POSTGRES_USER} WITH PASSWORD "
                    f"'{escaped_password}';"
                ),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if create.returncode != 0 and "already exists" not in (create.stderr or ""):
            raise StackProvisionError(
                create.stderr or create.stdout or "create database user failed",
            )

        create_db = subprocess.run(
            [
                "docker",
                "exec",
                "postgres",
                "psql",
                "-U",
                "postgres",
                "-c",
                f"CREATE DATABASE {db_name} OWNER {DEFAULT_POSTGRES_USER};",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if create_db.returncode != 0 and "already exists" not in (create_db.stderr or ""):
            raise StackProvisionError(create_db.stderr or create_db.stdout or "create database failed")

        restart = subprocess.run(
            ["docker", "restart", "pgbouncer"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        restart_log = (restart.stderr or restart.stdout or "").strip()
        return f"created database {db_name}" + (f"; {restart_log}" if restart_log else "")
