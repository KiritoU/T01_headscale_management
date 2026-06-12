---
name: headscale-headplane
description: >-
  Headscale and Headplane domain knowledge for multi-tenant operations. Use when
  integrating with Headscale API, designing tenant models, ACL/key workflows,
  node and route management, Headplane configuration, or gateway/workspace tags.
---

# Headscale + Headplane Domain

## Components

| Component | Role |
|-----------|------|
| **Headscale** | Self-hosted Tailscale control server — one tailnet per instance |
| **Headplane** | Web UI — machines, ACLs, DNS, OIDC, settings |
| **Tailscale client** | Device agent; registers to a Headscale `login-server` |

Official docs: [headscale.net](https://headscale.net/stable/), [headplane.net](https://headplane.net).

## Multi-tenant model

Headscale has **no native multi-tenancy**. This project uses **one Headscale + one Headplane per tenant**, distributed across VPS workers via the control plane.

```
Control plane
    ├── Worker VPS 1 → team-1, team-2, …
    └── Worker VPS 2 → team-N, …
```

Legacy single-host reference: [tenant-provisioning](../tenant-provisioning/SKILL.md).

## Naming conventions (from current deployment)

| Item | Pattern | Example |
|------|---------|---------|
| Tenant slug | `{suffix}-{n}` | `team-3` |
| DB name | `hs_{suffix}_{n}` | `hs_team_3` |
| Headscale URL | `https://headscale-{tenant}.{base_domain}` | — |
| Headplane URL | `https://headplane-{tenant}.{base_domain}` | — |
| Magic DNS | `tailnet-{tenant}.{base_domain}` | — |
| Container names | `headscale-{tenant}`, `headplane-{tenant}` | — |

## Shared stack per worker VPS

When multiple tenants share a worker (legacy pattern):

- **Traefik** — TLS (Cloudflare DNS-01 ACME)
- **Postgres + PgBouncer** — one database per tenant
- **Nginx** — serves per-tenant client scripts (`linux.sh`, `gateway.sh`, `window.ps1`)

## Headscale API

- **REST**: `/api/v1` on tenant's `server_url`
- **Auth**: `Authorization: Bearer <API_KEY>`
- **CLI** (in container): `docker exec headscale-{tenant} headscale <cmd>`
- **gRPC**: official interface for advanced automation

Match API version to deployed Headscale release per tenant.

## Core entities

| Entity | Description |
|--------|-------------|
| **User** | Tailnet identity (bootstrap creates `admin`) |
| **Machine / Node** | Registered device (gateway or workspace) |
| **Preauth key** | Registration key; tagged `tag:gateway` or `tag:workspace` |
| **API key** | Automation credential (`hskey-...`) |
| **ACL / Policy** | HuJSON; `policy.mode: database` after bootstrap |
| **Route** | Subnet route advertised by gateway node |
| **DNS** | MagicDNS + `dns_records.json` |

## Bootstrap sequence (standard per tenant)

Executed after containers are healthy:

```bash
headscale apikeys create
headscale users create admin -d Admin -o json
headscale preauthkeys create --user <id> --tags tag:gateway --reusable --expiration 365d
headscale preauthkeys create --user <id> --tags tag:workspace --reusable --expiration 365d
headscale policy set -f /etc/headscale/ACL.json
```

## ACL pattern (gateway + workspace)

```json
{
  "groups": { "group:gateway": [], "group:workspace": [] },
  "tagOwners": {
    "tag:gateway": ["group:gateway"],
    "tag:workspace": ["group:workspace"]
  },
  "autoApprovers": {
    "routes": { "192.168.0.0/16": ["tag:gateway"] }
  },
  "acls": [{ "action": "accept", "src": ["*"], "dst": ["*:*"] }]
}
```

Gateway nodes: see [gateway-management](../gateway-management/SKILL.md).

## Headplane integration

- Connects to Headscale via Docker network (`http://headscale-{tenant}:8080`)
- Docker integration: label `me.tale.headplane.target`, mount `docker.sock`
- CORS on Traefik: allow origin from matching Headplane hostname
- Config/dns_records volumes writable for UI edits

When automating tenant ops, prefer **Headscale API/CLI**; Headplane config for UI-specific settings.

## Operations at scale

1. Idempotent provisioning and bootstrap
2. Credential rotation (API keys, preauth keys)
3. Per-tenant health (containers + API + Headplane healthz)
4. Config drift (ACL, DNS, OIDC desired vs actual)
5. Bulk ops across tenants on same or different workers
6. Version pinning per tenant

## Security

- Store secrets as references; never log bearer tokens or preauth keys
- Tenant isolation is instance-level
- ACL/route changes are security-sensitive

## Additional resources

- CLI, API, tenant record fields: [reference.md](reference.md)
- Legacy compose layout: [tenant-provisioning/provisioning-reference.md](../tenant-provisioning/provisioning-reference.md)
