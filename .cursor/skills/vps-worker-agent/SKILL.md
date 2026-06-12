---
name: vps-worker-agent
description: >-
  Designs VPS worker agents with polling-based control plane communication and
  optional pluggable modules. Use when planning worker registration, command
  dispatch, tenant placement, or shared agent protocol with gateway agents.
---

# VPS Worker Agent

## Problem

Legacy: all tenants on one VPS via `generate-multi-tenants.sh`. Target: tenants distributed across VPS workers orchestrated by control plane.

## Roles

| Role | Responsibility |
|------|----------------|
| **Control plane** | Registry, command queue, module install requests, audit |
| **Worker agent** | Poll server, execute tenant/docker commands locally |
| **Gateway agent** | Same protocol; different command set (see gateway-management) |

## Connection model: polling (chosen)

**Outbound HTTP polling** from agent to server. No WebSocket. No inbound ports on worker/gateway.

```
Loop every N seconds:
  1. POST /api/v1/agents/{id}/heartbeat
  2. GET  /api/v1/agents/{id}/poll?since={cursor}
  3. For each item: execute → POST /api/v1/agents/{id}/commands/{cmd_id}/ack
```

| Benefit | Notes |
|---------|-------|
| NAT/firewall friendly | Agent initiates all traffic |
| Simple ops | Standard HTTP load balancers, retries |
| Module installs | Same poll queue delivers `install_module` |

Poll interval: default 15s (configurable per agent). Server holds commands until acknowledged.

## Pluggable modules (shared pattern)

Worker and gateway share **agent core + module registry**. Gateway modules: `tailscale`, `nmap`. Worker may add `docker`, `compose` modules later.

| Command | Description |
|---------|-------------|
| `install_module` | Server/UI triggers; agent runs module installer |
| *(tenant cmds)* | require relevant modules installed |

Module status reported in heartbeat: `installed_modules: ["docker", "compose"]`.

## Worker command categories

| Command | Local action |
|---------|--------------|
| `provision_tenant` | Generate config, compose services |
| `start_tenant` / `stop_tenant` | docker compose up/down |
| `bootstrap_tenant` | apikeys, admin, preauth, policy |
| `verify_tenant` | containers, headscale version, healthz |
| `update_acl` | policy set |
| `regenerate_scripts` | client scripts per tenant |

Commands idempotent; ack returns structured JSON (exit code, duration, sanitized logs).

## Tenant ↔ worker assignment

Control plane stores `tenant.worker_id`. Worker only executes commands for assigned tenants.

## Worker reports (via heartbeat + ack)

| Field | Content |
|-------|---------|
| heartbeat | capacity, docker reachable, tenant inventory, modules[] |
| command ack | success/fail, logs sanitized |

## Implementation phases

1. **Agent core** — register, poll, ack (shared with gateway)
2. **Worker-specific handlers** — tenant lifecycle commands
3. **Optional worker modules** — docker/compose as installable modules if not in base image

## Security

- Agent credential ≠ Headscale API key
- Poll + ack authenticated; scoped to agent_id
- Module installers fetched from control plane manifest

## Additional resources

- Gateway modules (tailscale, nmap): [gateway-management](../gateway-management/SKILL.md)
- Legacy ops to replicate: [tenant-provisioning](../tenant-provisioning/SKILL.md)
