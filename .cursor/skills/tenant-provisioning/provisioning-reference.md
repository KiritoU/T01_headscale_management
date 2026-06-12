# Provisioning reference (from generate-multi-tenants.sh)

## Directory layout after generate

```
multi-tenants/
├── compose.yml
├── .env
├── ACL.json
├── nginx.conf
├── traefik/acme/
├── postgres/
│   ├── data/
│   └── init/00-init.sql      # CREATE DATABASE hs_{suffix}_{n}
├── pgbouncer/
│   ├── pgbouncer.ini
│   ├── databases.ini
│   └── userlist.txt
├── scripts-root/
│   └── {tenant}/               # linux.sh, gateway.sh, window.ps1
├── tenants/
│   └── {tenant}/
│       ├── headscale/config.yaml
│       ├── headscale/dns_records.json
│       ├── headscale/data/
│       ├── headplane/config.yaml
│       └── headplane/data/
└── results/
    ├── verify.log
    ├── all-tenants.txt
    └── {tenant}.txt
```

## Postgres init SQL pattern

```sql
CREATE USER headscale WITH PASSWORD '...';
ALTER USER headscale CREATEDB;
CREATE DATABASE hs_team_1 OWNER headscale;
CREATE DATABASE hs_team_2 OWNER headscale;
-- ...
```

## PgBouncer databases.ini pattern

```ini
hs_team_1 = host=postgres port=5432 dbname=hs_team_1
hs_team_2 = host=postgres port=5432 dbname=hs_team_2
```

## Traefik labels (per Headscale)

- Router rule: `Host(\`headscale-{tenant}.{BASE_DOMAIN}\`)`
- CORS middleware allowing origin `https://headplane-{tenant}.{BASE_DOMAIN}`
- Label `me.tale.headplane.target=headscale-{tenant}` for Headplane Docker integration

## Regenerate without data loss

If `multi-tenants/` exists and user answers **not** `Yes` to clear:
- Reuse `POSTGRES_PASSWORD` / `PGBOUNCER_PASSWORD` from existing `.env`
- Overwrite compose and config files
- Postgres data volume preserved

## all-tenants.txt summary fields

Per tenant:
- `api_key` (from bootstrap)
- `auth_key_gateway` (preauth, tag:gateway)
- `auth_key_workspace` (preauth, tag:workspace)
- Client script curl check URLs

## Control plane tenant record (extended)

| Field | Maps from legacy |
|-------|------------------|
| `slug` | `{SUFFIX}-{N}` |
| `worker_id` | VPS running this tenant (null = legacy single-host) |
| `db_name` | `hs_{suffix}_{n}` |
| `base_domain` | `BASE_DOMAIN` |
| `headscale_host` | `headscale-{tenant}.{BASE_DOMAIN}` |
| `headplane_host` | `headplane-{tenant}.{BASE_DOMAIN}` |
| `tailnet_domain` | `tailnet-{tenant}.{BASE_DOMAIN}` |
| `download_host` | `DOWNLOAD_HOST` |
| `compose_project` | `multi-tenants` |
| `bootstrap_status` | pending / verified / bootstrapped / failed |
