---
name: gateway-management
description: >-
  Manages gateway agents with modular tailscale/nmap installs, polling-based
  server communication, custom tags, scan_network and tailscale_up commands.
  Use when designing gateway onboarding, module install from UI, or gateway ops.
---

# Gateway Management

## Gateway Agent architecture

**Core agent** (curl install) + **optional modules** (server-triggered install):

| Module | ID | Capability |
|--------|-----|------------|
| Core | `core` | Polling, enrollment, heartbeat, ip-route scan |
| Tailscale | `tailscale` | tailscaled, `tailscale_up`, `tailscale_status` |
| Nmap | `nmap` | `nmap -sn` live host discovery |

Operator clicks **"Cài module"** on UI → server queues `install_module` → agent picks up on next **poll**.

## Connection: polling

Gateway (and worker) agents use **outbound HTTP polling** — not WebSocket.

```
Agent --heartbeat--> Server
Agent <--poll------- Server (pending commands + module installs)
Agent --ack--------> Server
```

See [gateway-agent.md](gateway-agent.md) for endpoint sketch.

## Install

```bash
curl -LsSf https://get.{DOMAIN}/gateway-agent.sh | sh
```

Installs **core only**. Tailscale/nmap added later from server UI.

## Remote commands

| Command | Requires module |
|---------|-----------------|
| `install_module` | core (runs installer) |
| `scan_network` | core; nmap optional for live hosts |
| `tailscale_up` | **tailscale** |
| `tailscale_status` | **tailscale** |

## Custom tags

Server assigns custom tags per gateway; applied on `tailscale_up` (tailscale module).

## UI (Phase 7)

- Module badges + install buttons per gateway
- Scan → subnet table (ip-route always; nmap enriches if installed)
- Reconnect → `tailscale_up` (disabled until tailscale module installed)
- Enrollment curl URL copy

## Data model additions

| Entity | Fields |
|--------|--------|
| `AgentModule` | `agent_id`, `module_id`, `status`, `version`, `installed_at` |
| `ModuleInstallRequest` | `agent_id`, `module_id`, `status` |

## Additional resources

- Polling + modules detail: [gateway-agent.md](gateway-agent.md)
- Shared agent protocol: [vps-worker-agent](../vps-worker-agent/SKILL.md)
- Legacy gateway.sh: tenant-provisioning skill
