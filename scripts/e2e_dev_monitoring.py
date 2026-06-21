#!/usr/bin/env python3
"""E2E monitoring validation for gateway dev (admin/admin)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
DEV_GATEWAY_ID = "06ec72af-662b-4483-90be-2a9c44e1b132"
AGENT_ID = "09a2208f-3a6a-46d3-94af-ddebdc8878c9"
AGENT_TOKEN = Path("/tmp/gateway-test.env").read_text() if Path("/tmp/gateway-test.env").exists() else ""
for line in AGENT_TOKEN.splitlines():
    if line.startswith("AGENT_TOKEN="):
        AGENT_TOKEN = line.split("=", 1)[1].strip().strip('"')
        break


def main() -> int:
    client = httpx.Client(base_url=BASE, timeout=30.0, follow_redirects=True)
    csrf = client.get("/api/auth/csrf/").json()["data"]["csrf_token"]
    login = client.post(
        "/api/auth/login/",
        json={"username": "admin", "password": "admin"},
        headers={"X-CSRFToken": csrf, "Referer": BASE},
    )
    login.raise_for_status()
    assert login.json()["success"] is True, login.text
    csrf = client.cookies.get("csrftoken", csrf)

    policy_patch = {
        "enabled": True,
        "vuln_scan_enabled": True,
        "discover_interval_minutes": 60,
        "vuln_rescan_days": 1,
        "nuclei_enabled": True,
        "monitored_cidrs": ["192.168.100.0/24"],
        "vuln_parallel_workers": 4,
        "scan_strategy": "rotating_chunks",
        "chunk_count": 4,
    }
    patch = client.patch(
        f"/api/gateways/{DEV_GATEWAY_ID}/monitoring/",
        json=policy_patch,
        headers={"X-CSRFToken": csrf, "Referer": BASE},
    )
    if patch.status_code != 200:
        print("PATCH failed:", patch.status_code, patch.text)
        return 1
    policy = patch.json()["data"]
    print("policy min_interval:", policy["min_interval_minutes"])
    print("policy vuln_rescan_days:", policy["vuln_rescan_days"])
    print("policy nuclei_enabled:", policy["nuclei_enabled"])
    assert policy["min_interval_minutes"] >= 10
    assert policy["vuln_rescan_days"] == 1
    assert policy["nuclei_enabled"] is True

    ensure = client.post(
        f"/api/gateways/{DEV_GATEWAY_ID}/monitoring/modules/ensure/",
        headers={"X-CSRFToken": csrf, "Referer": BASE},
    )
    ensure.raise_for_status()
    print("ensure ready:", ensure.json()["data"]["ready"])

    # wait for module installs
    for i in range(24):
        time.sleep(5)
        pol = client.get(f"/api/gateways/{DEV_GATEWAY_ID}/monitoring/").json()["data"]
        statuses = {m["module_id"]: m["status"] for m in pol["module_statuses"]}
        print(f"modules [{i}]:", statuses)
        needed = ["masscan", "nmap", "vuln-nse-pack", "iot-probes"]
        if pol.get("nuclei_enabled"):
            needed.append("nuclei")
        if all(statuses.get(m) == "installed" for m in needed):
            break

    scan = client.post(
        f"/api/gateways/{DEV_GATEWAY_ID}/commands/",
        json={"command": "scan_network", "payload": {"mode": "monitor", "targets": ["192.168.100.0/24"]}},
        headers={"X-CSRFToken": csrf, "Referer": BASE},
    )
    scan.raise_for_status()
    cmd_id = scan.json()["data"]["id"]
    print("scan command:", cmd_id)

    for i in range(30):
        time.sleep(3)
        cmd = client.get(
            f"/api/gateways/{DEV_GATEWAY_ID}/commands/{cmd_id}/",
            headers={"X-CSRFToken": csrf, "Referer": BASE},
        ).json()["data"]
        print(f"scan state [{i}]:", cmd["state"])
        if cmd["state"] in ("acked", "failed"):
            break

    hosts = client.get(f"/api/gateways/{DEV_GATEWAY_ID}/monitoring/hosts/").json()["data"]
    print("hosts:", len(hosts))

    agent = httpx.Client(
        base_url=BASE,
        timeout=30.0,
        headers={"Authorization": f"Bearer {AGENT_TOKEN}"},
    )
    for i in range(40):
        time.sleep(5)
        queue = agent.get(f"/api/v1/agents/{AGENT_ID}/monitoring/vuln-queue/").json()
        pending = sum(1 for h in hosts if h.get("vuln_scan_pending"))
        findings = client.get(f"/api/gateways/{DEV_GATEWAY_ID}/monitoring/findings/").json()["data"]
        nuclei_findings = [f for f in findings if f.get("source") == "nuclei"]
        print(
            f"vuln [{i}] queue={len(queue.get('targets', []))} pending_hosts={pending} "
            f"findings={len(findings)} nuclei={len(nuclei_findings)}",
        )
        if queue.get("targets"):
            print("  queue modules sample:", queue["targets"][0].get("modules"))
        scanned = sum(1 for h in client.get(f"/api/gateways/{DEV_GATEWAY_ID}/monitoring/hosts/").json()["data"] if h.get("last_vuln_scan_at"))
        if scanned >= len(hosts) and len(hosts) > 0:
            print("PASS: all hosts vuln-scanned")
            print(json.dumps({
                "min_interval": policy["min_interval_minutes"],
                "hosts": len(hosts),
                "findings": len(findings),
                "nuclei_findings": len(nuclei_findings),
                "scanned_hosts": scanned,
            }, indent=2))
            return 0

    print("FAIL: vuln scan did not complete for all hosts")
    return 1


if __name__ == "__main__":
    sys.exit(main())
