#!/usr/bin/env python3
"""End-to-end enrollment test against Docker Compose stack."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

BASE = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8081")
USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
POLL_SECONDS = int(os.environ.get("ENROLL_POLL_SECONDS", "300"))


def login(client: httpx.Client) -> str:
    csrf = client.get("/api/auth/csrf/").json()["data"]["csrf_token"]
    login = client.post(
        "/api/auth/login/",
        json={"username": USERNAME, "password": PASSWORD},
        headers={"X-CSRFToken": csrf, "Referer": BASE},
    )
    login.raise_for_status()
    assert login.json()["success"] is True
    return client.cookies.get("csrftoken", csrf)


def auth_headers(client: httpx.Client) -> dict[str, str]:
    csrf = client.cookies.get("csrftoken") or client.get("/api/auth/csrf/").json()["data"]["csrf_token"]
    return {"X-CSRFToken": csrf, "Referer": BASE}


def wait_for(predicate, *, label: str, timeout: int = POLL_SECONDS) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(2)
    raise TimeoutError(f"Timed out waiting for {label}")


def run_install_script(install_command: str, *, label: str) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["SKIP_SYSTEMD"] = "1"
    env["INSTALL_DIR"] = tempfile.mkdtemp(prefix=f"hs-{label}-")
    print(f"[RUN] {label} install into {env['INSTALL_DIR']}")
    proc = subprocess.Popen(
        ["bash", "-lc", install_command],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


def main() -> int:
    failures: list[str] = []
    client = httpx.Client(base_url=BASE, timeout=30.0, follow_redirects=True)

    try:
        login(client)
        headers = auth_headers(client)

        config = client.get("/api/config/").json()["data"]
        public_base = config.get("public_base_url", "")
        if not public_base:
            failures.append("public_base_url missing from /api/config/")
        else:
            print(f"[OK] public_base_url={public_base}")

        worker_name = f"docker-e2e-worker-{int(time.time())}"
        worker_resp = client.post(
            "/api/workers/enrollment-tokens/",
            json={"name": worker_name, "expires_in_minutes": 60},
            headers=headers,
        )
        worker_resp.raise_for_status()
        worker_data = worker_resp.json()["data"]
        worker_id = worker_data["worker_id"]
        install_command = worker_data["install_command"]
        assert "curl -fsSL" in install_command
        assert "| bash" in install_command
        assert "CONTROL_PLANE_URL=" not in install_command
        print(f"[OK] worker install_command generated")

        worker_proc = run_install_script(install_command, label="worker")

        def worker_online() -> bool:
            workers_body = client.get("/api/workers/").json()
            workers = (
                workers_body.get("data", [])
                if isinstance(workers_body, dict)
                else workers_body
            )
            match = next((item for item in workers if item["id"] == worker_id), None)
            return match is not None and match.get("status") == "online"

        try:
            wait_for(worker_online, label=f"worker {worker_id} online")
            print(f"[OK] worker {worker_id} is online")
        finally:
            if worker_proc.poll() is None:
                worker_proc.kill()
                try:
                    worker_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    worker_proc.kill()

        tenants_body = client.get("/api/tenants/").json()
        tenants = (
            tenants_body.get("data", [])
            if isinstance(tenants_body, dict)
            else tenants_body
        )
        if not tenants:
            slug = f"e2e-{int(time.time())}"
            tenant_resp = client.post(
                "/api/tenants/",
                json={
                    "slug": slug,
                    "headscale_host": f"{slug}.hs.local",
                    "headplane_host": f"{slug}.hp.local",
                    "db_name": slug.replace("-", "_"),
                },
                headers=headers,
            )
            tenant_resp.raise_for_status()
            tenant_body = tenant_resp.json()
            tenant_id = tenant_body.get("id") or tenant_body.get("data", {}).get("id")
            print(f"[OK] created tenant {tenant_id}")
        else:
            tenant_id = tenants[0]["id"]
            print(f"[OK] using existing tenant {tenant_id}")

        gateway_resp = client.post(
            f"/api/tenants/{tenant_id}/gateways/enrollment-tokens/",
            json={"max_uses": 1},
            headers=headers,
        )
        gateway_resp.raise_for_status()
        gateway_data = gateway_resp.json()["data"]
        gateway_install = gateway_data["install_command"]
        assert gateway_data.get("expires_at") is not None
        print(f"[OK] gateway install_command generated")

        gateway_proc = run_install_script(gateway_install, label="gateway")

        def gateway_enrolled() -> bool:
            gateways_body = client.get("/api/gateways/").json()
            gateways = (
                gateways_body.get("data", [])
                if isinstance(gateways_body, dict)
                else gateways_body
            )
            return any(item.get("status") in {"enrolled", "online"} for item in gateways)

        try:
            wait_for(gateway_enrolled, label="gateway enrolled")
            print("[OK] gateway enrolled")
        finally:
            if gateway_proc.poll() is None:
                gateway_proc.terminate()
                try:
                    gateway_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    gateway_proc.kill()

        bundle = client.get("/api/workers/agent-daemon-bundle.tar.gz")
        assert bundle.status_code == 200
        assert len(bundle.content) > 100
        print("[OK] agent daemon bundle downloadable")

    except Exception as exc:  # noqa: BLE001
        failures.append(str(exc))
        print(f"[FAIL] {exc}", file=sys.stderr)

    print()
    if failures:
        print("Enrollment test failed.")
        return 1
    print("Enrollment E2E passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
