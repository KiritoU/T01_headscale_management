# Headscale Management — Backend

Django control plane for Headscale + Headplane tenants, VPS workers, and gateway agents.

## Prerequisites

- [uv](https://docs.astral.sh/uv/) — Python package manager and runner
- [Docker](https://docs.docker.com/) — local PostgreSQL (production-like dev database)

## Quick start

From `backend/`:

```bash
cp .env.example .env
docker compose up -d
uv sync
uv run python manage.py migrate
uv run python manage.py runserver
```

The dev server listens on `http://127.0.0.1:8000/`.

Postgres credentials in `.env` match `docker-compose.yml` (`headscale` / `headscale_mgmt` on port `5432`).

## Testing

```bash
uv run pytest
```

Pytest uses an in-memory SQLite database automatically (no Postgres required).

To run other Django commands without Postgres (e.g. `check`, `migrate` in CI):

```bash
DJANGO_TEST=1 uv run python manage.py check
```

`DJANGO_TEST=1` switches the default database to SQLite (`:memory:`).

## API endpoints

| Path | Description |
|------|-------------|
| `GET /api/health/` | Health check (JSON envelope) |
| `GET /api/schema/` | OpenAPI schema (drf-spectacular) |
| `GET /gateway-agent.sh` | Gateway agent install script |

Interactive docs: `GET /api/docs/` (Swagger UI).

## Project structure

```
backend/
├── config/           # Django settings, root URLconf, WSGI/ASGI
├── core/             # Health endpoint, API responses, script serving
├── tenants/          # Tenant registry (Headscale + Headplane instances)
├── workers/          # VPS worker hosts and placement
├── gateways/         # Per-tenant gateway agents
├── scripts/          # gateway-agent.sh (served at /gateway-agent.sh)
├── tests/            # Cross-app integration tests
├── manage.py
├── pyproject.toml    # Dependencies and tool config (uv)
├── docker-compose.yml
└── .env.example
```

### Apps

| App | Role |
|-----|------|
| `core` | Shared utilities, health check, gateway script endpoint |
| `tenants` | Tenant model and lifecycle (bootstrap status, worker FK) |
| `workers` | Worker registration, heartbeat, Docker reachability |
| `gateways` | Gateway enrollment and status per tenant |

All commands use `uv run` — do not invoke `pip` or bare `python` directly.
