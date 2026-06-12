---
name: tenant-provisioning
description: >-
  Documents the legacy generate-multi-tenants.sh provisioning workflow used to
  spin up many Headscale+Headplane tenants on one VPS. Use when designing tenant
  lifecycle, migration from bash to control plane, reproducing bootstrap steps,
  or understanding current naming, compose, and credential patterns.
---

# Tenant Provisioning (Legacy Baseline)

## Source of truth

Script: `/root/headscale-multi-tenants/generate-multi-tenants.sh`

Output directory: `multi-tenants/` (compose, configs, results).

This is the **current production pattern** the control plane will eventually replace. Preserve behavioral parity when migrating.

## What the script generates

### Shared infrastructure (one stack per VPS)

| Service | Role |
|---------|------|
| **Traefik v3** | TLS termination; Let's Encrypt DNS-01 via Cloudflare |
| **Postgres 16** | Shared DB server |
| **PgBouncer** | Connection pooler; one DB alias per tenant |
| **Nginx** | Serves per-tenant client setup scripts |

### Per tenant

| Artifact | Pattern |
|----------|---------|
| Tenant ID | `{SUFFIX}-{N}` (default `team-1`, `team-2`, …) |
| Postgres DB | `hs_{suffix}_{n}` (e.g. `hs_team_3`) |
| Headscale host | `headscale-{tenant}.{BASE_DOMAIN}` |
| Headplane host | `headplane-{tenant}.{BASE_DOMAIN}` |
| Magic DNS base | `tailnet-{tenant}.{BASE_DOMAIN}` |
| Containers | `headscale-{tenant}`, `headplane-{tenant}` |
| Client scripts | `scripts-root/{tenant}/linux.sh`, `gateway.sh`, `window.ps1` |
| Script download | `https://{DOWNLOAD_HOST}/{tenant}/<script>` |

### Environment inputs

| Variable | Purpose |
|----------|---------|
| `TENANTS` | Count to generate |
| `SUFFIX` | Tenant name prefix (default `team`) |
| `BASE_DOMAIN` | Root domain for all hostnames |
| `DOWNLOAD_HOST` | Host serving client scripts (default `download.{BASE_DOMAIN}`) |
| `ACME_EMAIL` | Let's Encrypt registration |
| `CF_DNS_API_TOKEN` | Cloudflare DNS API for ACME DNS-01 |

Secrets in `multi-tenants/.env`: `POSTGRES_PASSWORD`, `PGBOUNCER_PASSWORD`, `CF_DNS_API_TOKEN`.

## Headscale config pattern (per tenant)

- `server_url`: `https://headscale-{tenant}.{BASE_DOMAIN}`
- Postgres via PgBouncer (`host: pgbouncer`, `port: 6432`, `name: hs_{suffix}_{n}`)
- `policy.mode: database` — ACL stored in DB after bootstrap
- Magic DNS enabled with per-tenant `base_domain`
- Shared `ACL.json` mounted read-only into each Headscale container

## Headplane config pattern (per tenant)

- Internal Headscale URL: `http://headscale-{tenant}:8080` (Docker network)
- Public URL: `https://headscale-{tenant}.{BASE_DOMAIN}`
- Docker integration enabled (`container_name`, `docker.sock`)
- Random `cookie_secret` and local admin password per tenant

## Bootstrap sequence (after `docker compose up -d`)

For each healthy tenant, via `docker exec headscale-{tenant}`:

1. `headscale apikeys create` → automation key
2. `headscale users create admin -d Admin -o json` → parse `user_id`
3. `headscale preauthkeys create --user <id> --tags tag:gateway --reusable --expiration 365d`
4. `headscale preauthkeys create --user <id> --tags tag:workspace --reusable --expiration 365d`
5. `headscale policy set -f /etc/headscale/ACL.json`

Results: `multi-tenants/results/{tenant}.txt`, summary in `all-tenants.txt`.

## Verify sequence

Per tenant before bootstrap:

1. Container `headscale-{tenant}` running
2. Container `headplane-{tenant}` running
3. `docker exec … headscale version` succeeds
4. Headplane healthy (`/admin/healthz` or Docker HEALTHCHECK)

## Shared ACL template

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

Gateway routes in `192.168.0.0/16` are auto-approved for `tag:gateway` nodes.

## Client script generation

Templates in `template/client-setup/`; per tenant only `LOGIN_SERVER` is substituted:

```
LOGIN_SERVER="https://headscale-{tenant}.{BASE_DOMAIN}"
```

- `linux.sh` — workspace client (`--accept-routes`, `tag:workspace` key)
- `gateway.sh` — subnet router (`--advertise-routes`, `tag:gateway` key)
- `window.ps1` — Windows workspace client

## Control plane migration goals

When replacing this script, the backend should:

1. Store tenant + worker assignment (which VPS runs which tenants)
2. Emit equivalent compose/config (or incremental patches) to workers
3. Run the same bootstrap steps idempotently
4. Track credentials in secrets store, not plaintext files
5. Support regenerate without destroying Postgres data (reuse `.env` passwords pattern)

## Additional resources

- File layout and compose details: [provisioning-reference.md](provisioning-reference.md)
