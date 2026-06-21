#!/usr/bin/env python3
"""Smoke-test the Docker Compose stack."""
from __future__ import annotations

import os
import sys

import httpx

BASE = os.environ.get("SMOKE_BASE_URL", "http://127.0.0.1:8081")
USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=30.0, follow_redirects=True)
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        status = "OK" if ok else "FAIL"
        print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    # Static UI
    ui = client.get("/")
    check("frontend index", ui.status_code == 200 and "html" in ui.headers.get("content-type", ""))

    # CSRF + login
    csrf_body = client.get("/api/auth/csrf/").json()
    csrf = csrf_body.get("data", {}).get("csrf_token", "")
    check("csrf endpoint", bool(csrf))

    login = client.post(
        "/api/auth/login/",
        json={"username": USERNAME, "password": PASSWORD},
        headers={"X-CSRFToken": csrf, "Referer": BASE},
    )
    check("login", login.status_code == 200 and login.json().get("success") is True, login.text[:120])

    csrf = client.cookies.get("csrftoken", csrf)

    me = client.get("/api/auth/me/")
    me_user = me.json().get("data", {}).get("user", {})
    check("auth me", me.status_code == 200 and me_user.get("username") == USERNAME)

    gateways = client.get("/api/gateways/")
    check("gateways list", gateways.status_code == 200 and gateways.json().get("success") is True)

    if gateways.json().get("data"):
        gateway_id = gateways.json()["data"][0]["id"]
        monitoring = client.get(f"/api/gateways/{gateway_id}/monitoring/")
        check("monitoring policy", monitoring.status_code == 200)

        hosts = client.get(
            f"/api/gateways/{gateway_id}/monitoring/hosts/",
            params={"page": 1, "limit": 5},
        )
        meta = hosts.json().get("meta", {})
        check(
            "monitoring hosts pagination",
            hosts.status_code == 200 and "total" in meta,
            f"total={meta.get('total')}",
        )

        findings = client.get(
            f"/api/gateways/{gateway_id}/monitoring/findings/",
            params={"page": 1, "limit": 5},
        )
        check(
            "monitoring findings pagination",
            findings.status_code == 200 and "pages" in findings.json().get("meta", {}),
        )
    else:
        print("[SKIP] no gateways enrolled — monitoring API checks skipped")

    agent_script = client.get("/gateway-agent.sh")
    check("gateway-agent.sh", agent_script.status_code == 200 and "bash" in agent_script.text[:20].lower())

    print()
    if failures:
        print(f"Smoke test failed: {', '.join(failures)}")
        return 1
    print("All smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
