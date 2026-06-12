# Headscale / Headplane reference

## Headscale CLI (per tenant container)

```bash
docker exec -i headscale-team-1 headscale version
docker exec -i headscale-team-1 headscale users list
docker exec -i headscale-team-1 headscale nodes list
docker exec -i headscale-team-1 headscale routes list
docker exec -i headscale-team-1 headscale apikeys create
docker exec -i headscale-team-1 headscale preauthkeys create --user <id> --tags tag:gateway --reusable --expiration 365d
docker exec -i headscale-team-1 headscale policy set -f /etc/headscale/ACL.json
```

## REST patterns (verify against deployed version)

```http
GET /api/v1/user
GET /api/v1/machine
GET /api/v1/routes
POST /api/v1/preauthkey
```

Auth: `Authorization: Bearer <API_KEY>` where key format is `hskey-...`.

## Route management (gateways)

```bash
headscale routes list
headscale routes enable -r <route_id>
```

Auto-approval applies when ACL `autoApprovers.routes` matches advertised CIDR and node has `tag:gateway`.

## Tenant record (control plane)

| Field | Purpose |
|-------|---------|
| `slug` | e.g. `team-1` |
| `worker_id` | VPS worker hosting this tenant |
| `db_name` | `hs_team_1` |
| `headscale_url` | Public API URL |
| `headplane_url` | UI URL |
| `tailnet_domain` | Magic DNS base |
| `api_key_ref` | Secret reference |
| `headscale_version` | Image tag pin |
| `status` | provisioning / active / suspended / deleted |
| `bootstrap_status` | pending / bootstrapped / failed |
| `config_desired` | ACL, DNS, OIDC (JSON) |
| `last_health_at` | Last probe timestamp |

## Gateway record (separate module)

| Field | Purpose |
|-------|---------|
| `tenant_id` | Parent tailnet |
| `node_id` | Headscale machine ID |
| `tailscale_ip` | 100.x address |
| `hostname` | Node name |
| `tags` | Must include `tag:gateway` |
| `advertised_routes` | List of CIDRs |
| `routes_approved` | Approval state per CIDR |
| `last_seen_at` | Connectivity |

## Health checks

**Tenant stack (worker-local):**
1. `headscale-{tenant}` container running
2. `headplane-{tenant}` container running
3. `headscale version` succeeds
4. `GET /admin/healthz` on Headplane

**Tenant API (control plane):**
1. Authenticated Headscale API call
2. Optional Headplane HTTPS reachability

**Gateway (tailnet node):**
1. Node present in `headscale nodes list`
2. Routes listed and enabled
3. Optional: probe via tailnet if control plane has access

## Client script URLs (legacy)

```
https://{DOWNLOAD_HOST}/{tenant}/linux.sh      # workspace
https://{DOWNLOAD_HOST}/{tenant}/gateway.sh    # subnet router
https://{DOWNLOAD_HOST}/{tenant}/window.ps1    # Windows workspace
```

## Version coupling

- Pin Headscale image per tenant; Headplane must match compatibility matrix.
- Check release notes when upgrading either side on a worker.
