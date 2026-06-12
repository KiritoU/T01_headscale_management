# Gateway Agent Reference

## One-liner install (core only)

```bash
curl -LsSf https://get.{CONTROL_PLANE_DOMAIN}/gateway-agent.sh | sh
```

Core agent is **minimal** — Tailscale và nmap là **modules** cài thêm từ server (nút trên UI).

```bash
curl -LsSf "https://get.{DOMAIN}/gateway-agent.sh?token=ENROLL_TOKEN" | sh
```

Core responsibilities:
1. Install gateway agent daemon (systemd)
2. Register with control plane (enrollment token)
3. **Poll** server for commands and module install requests
4. Run built-in `network-routes` scan (ip route/addr — no extra deps)

## Connection: polling (not WebSocket)

Agent **outbound polls** control plane on interval:

```
┌─────────┐  POST /heartbeat          ┌──────────────┐
│ Gateway │ ───────────────────────► │ Control plane│
│  Agent  │  GET  /poll?since=...    │              │
│         │ ◄─────────────────────── │ pending cmds │
│         │  POST /commands/{id}/ack │              │
└─────────┘ ───────────────────────► └──────────────┘
```

| Endpoint (illustrative) | Direction | Payload |
|-------------------------|-----------|---------|
| `POST .../heartbeat` | Agent → server | status, installed_modules[], agent_version |
| `GET .../poll` | Agent → server | Returns: commands[], `install_module` requests |
| `POST .../commands/{id}/ack` | Agent → server | result JSON, exit code, duration |
| `POST .../modules/{name}/status` | Agent → server | installing / installed / failed |

**Poll interval:** configurable (e.g. 10–30s). Server holds commands until polled.

Same polling pattern applies to **worker agent** — one shared agent protocol.

## Pluggable modules

| Module | ID | Provides | Install triggered by |
|--------|-----|----------|----------------------|
| *(core)* | `core` | poll loop, enrollment, `network-routes` scan | curl install |
| Tailscale | `tailscale` | `tailscaled`, `tailscale` CLI, `tailscale_up`, `tailscale_status` | Server UI button → `install_module` |
| Nmap | `nmap` | `nmap -sn` host discovery on subnets | Server UI button → `install_module` |

### install_module command

Server dispatches when operator clicks "Cài module Tailscale" / "Cài module Nmap":

```json
{
  "type": "install_module",
  "module": "tailscale",
  "params": {}
}
```

Agent runs module installer script, reports progress via `modules/{name}/status`, then ack.

**Command gating:** Agent rejects (or queues) `tailscale_up` if `tailscale` module not installed; `scan_network` with nmap requires `nmap` module.

### scan_network (uses modules)

| Step | Module required | Action |
|------|-----------------|--------|
| Interface/route discovery | `core` only | `ip -4 route`, `ip -4 addr` |
| Live host count per CIDR | `nmap` | `nmap -sn <cidr>` |

Response:

```json
{
  "subnets": [
    {"cidr": "192.168.1.0/24", "interface": "eth0", "source": "ip-route", "live_hosts": null},
    {"cidr": "192.168.1.0/24", "interface": "eth0", "source": "nmap", "live_hosts": 12}
  ],
  "modules_used": ["core", "nmap"],
  "modules_missing": []
}
```

If `nmap` not installed: return ip-route subnets only + `modules_missing: ["nmap"]` hint in UI.

### tailscale_up (requires tailscale module)

| Param | CLI flag | Gateway default |
|-------|----------|-----------------|
| `login_server` | `--login-server=` | Tenant Headscale URL |
| `auth_key` | `--authkey=` | Ephemeral ref |
| `advertise_routes` | `--advertise-routes=` | Selected CIDRs |
| `force_reauth` | `--force-reauth` | true |
| `accept_dns` | `--accept-dns` | true |
| `accept_routes` | `--accept-routes` | **false** |
| `reset` | `--reset` | true on re-enroll |

Executed by **tailscale module** only when module status = `installed`.

## Server-assigned tags

Applied on `tailscale_up` via tailscale module. Custom tags from operator UI; base `tag:gateway` from preauth.

## UI: module management per gateway

| UI action | Server dispatches |
|-----------|-------------------|
| "Cài Tailscale" | `install_module: tailscale` |
| "Cài Nmap" | `install_module: nmap` |
| Badge | `installed` / `not_installed` / `installing` / `failed` per module |
| "Quét mạng" | `scan_network` (uses available modules) |
| "Kết nối lại" | `tailscale_up` (requires tailscale) |

## Enrollment flow

1. Operator creates enrollment token per tenant
2. Client runs curl → core agent only
3. Agent polls → server shows gateway online, modules empty
4. Operator installs modules from UI → agent polls `install_module`
5. Operator runs scan / tailscale_up when modules ready

## Security

- Enrollment tokens tenant-scoped, revocable
- Module install scripts fetched from control plane (signed URL or embedded manifest)
- Auth keys ephemeral — not in logs
- Poll requests authenticated with agent credential
