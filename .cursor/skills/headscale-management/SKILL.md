---
name: headscale-management
description: >-
  Guides development of the headscale-management control plane for operating
  many Headplane+Headscale tenants across one or more VPS workers, plus gateway
  node management. Use when working in this repository, planning architecture,
  scaffolding backend/frontend, or designing tenant/worker/gateway features.
---

# Headscale Management Platform

## Project purpose

Central **control plane** to provision, configure, monitor, and operate a large number of **Headscale + Headplane tenants** distributed across **one or more VPS workers**.

Headscale has no native multi-tenancy (one instance = one tailnet). Each tenant is an isolated Headscale instance (usually paired with Headplane). Tenants may run on the **same VPS as the control server** or on **separate VPS hosts**.

## Three functional domains

| Domain | Responsibility |
|--------|----------------|
| **Tenant orchestration** | Lifecycle, config, keys, health, bulk ops across tenants |
| **VPS worker agents** | Remote hosts connect to control plane, receive commands, execute tenant ops locally |
| **Gateway management** | Gateway **agent** (curl install), custom tags, remote commands (`scan_network`, `tailscale_up`), routes UI |

These are separate concerns in code and UI; gateway management is not just a subset of tenant CRUD.

## Architecture evolution

### Legacy baseline (current manual process)

Reference implementation: `/root/headscale-multi-tenants/generate-multi-tenants.sh`

Single VPS runs everything in one Docker Compose stack:
- Shared Traefik, Postgres, PgBouncer, Nginx (client scripts)
- N × (Headscale + Headplane) per tenant
- Script generates config, `docker compose up`, verify, bootstrap keys/ACL

See [tenant-provisioning](../tenant-provisioning/SKILL.md) for full details.

### Target architecture (this project)

```
┌─────────────────────────────────────────┐
│  Control plane (headscale-management)   │
│  backend API + frontend UI              │
└──────────────┬──────────────────────────┘
               │ poll / heartbeat / commands
       ┌───────┴───────┐
       ▼               ▼
┌─────────────┐ ┌─────────────┐
│  VPS worker │ │  VPS worker │  (same host as control OR remote)
│  tenants A… │ │  tenants M… │
└─────────────┘ └─────────────┘

Gateway agents (curl install, tag:gateway + custom tags) ──tailscale up──► tenant tailnets
```

Control plane owns **desired state** (tenant registry, assignments, credentials refs). Workers own **local execution** (compose, docker exec, file generation). Agents connect via **HTTP polling** (not WebSocket). See [vps-worker-agent](../vps-worker-agent/SKILL.md).

## Tech stack

| Layer | Stack | Notes |
|-------|-------|-------|
| Backend | Python + **uv** | Always `uv add` / `uv remove`; run via `uv run` |
| Frontend | TBD | Scaffold when requirements are defined |
| Agents | Poll loop (worker + gateway) | HTTP polling; modules: tailscale, nmap on gateway |
| Targets | Headscale API, Headplane, Tailscale gateway nodes | Per tenant / per gateway |

## Repository conventions

### Backend rules (mandatory)

1. Dependencies: `uv add` / `uv remove` only — never `pip install`, never hand-edit dependency lists.
2. Scaffolding: prefer framework CLIs (`django-admin startapp`, `makemigrations`, …).
3. Execution: `uv run` for all Python commands.

### Scope

- Minimize diff; match existing patterns.
- Do not implement worker protocol or gateway features until scoped — but design models/APIs with these domains in mind.
- Legacy bash script is **reference**, not code to copy into backend verbatim.

## Planned layout

```
headscale-management/
├── backend/          # Control plane API (uv project)
├── frontend/         # Web UI (stack TBD)
└── .cursor/skills/
```

Worker agent code may live in `backend/` (shared models) + separate deployable package later.

## Core domain concepts

| Concept | Meaning |
|---------|---------|
| **Tenant** | One tailnet: Headscale (+ Headplane), named e.g. `team-1` |
| **Worker / VPS** | Host that runs one or more tenant stacks; reports to control plane |
| **Gateway** | Tailscale node with `tag:gateway`, advertises subnets into a tenant tailnet |
| **Workspace node** | Regular client with `tag:workspace`, uses `--accept-routes` |
| **Control plane** | This platform — orchestrates, does not replace Headscale |

## Frontend / UI design

| Tool | Role |
|------|------|
| [ui-ux-pro-max](../ui-ux-pro-max/SKILL.md) | UX intelligence, stack guidelines, design-system generator (auto on UI tasks) |
| [awesome-design-md](../awesome-design-md/SKILL.md) | Visual contract via `DESIGN.md` (Supabase-inspired dark admin) |
| `design-system/headscale-management/` | Persisted UX patterns from ui-ux-pro-max |

**Default UI:** dark infrastructure dashboard — tenant tables, worker status, gateway routes.

## Agent harness tooling (installed)

| Tool | Role | Reinstall |
|------|------|-----------|
| **ECC** (Everything Claude Code) | Rules, hooks, agents, coding workflow skills (Python + TypeScript rules) | `ecc-install --config ecc-install.json` |
| **GSD Core** | Spec-driven development — phases, planning, execution, verify | `npx @opengsd/gsd-core@latest --cursor --local --profile=core` |

### GSD workflow (mention skill name in Cursor)

```
gsd-new-project     # Initialize PROJECT.md, roadmap, requirements
gsd-discuss-phase   # Capture implementation decisions for a phase
gsd-plan-phase      # Create executable plans
gsd-execute-phase   # Execute plans
gsd-help            # List commands and workflow help
```

GSD artifacts land in `.planning/` (gitignored). Human-readable plan: `DEVELOPMENT-PLAN.md`.

### ECC notes

- Install state: `.cursor/ecc-install-state.json`, config: `ecc-install.json`
- Hooks: `.cursor/hooks.json` (session, shell guard, format-on-save reminders)
- Python rules: `.cursor/rules/python-*.mdc`
- Optional: `export ECC_AGENT_DATA_HOME="$HOME/.cursor/ecc"` to isolate ECC memory from other harnesses

## Agent workflow

1. This skill — project context and architecture.
2. [uv-python-backend](../uv-python-backend/SKILL.md) — Python/uv rules.
3. [headscale-headplane](../headscale-headplane/SKILL.md) — Headscale/Headplane APIs and entities.
4. [tenant-provisioning](../tenant-provisioning/SKILL.md) — legacy `generate-multi-tenants.sh` baseline to replace.
5. [vps-worker-agent](../vps-worker-agent/SKILL.md) — distributed execution on VPS.
6. [gateway-management](../gateway-management/SKILL.md) — gateway node operations.
7. UI work → [awesome-design-md](../awesome-design-md/SKILL.md) + [ui-ux-pro-max](../ui-ux-pro-max/SKILL.md).
8. New feature phases → GSD skills (`gsd-new-project`, `gsd-plan-phase`, `gsd-execute-phase`).
9. Code quality / TDD / review → ECC skills (`tdd-workflow`, `verification-loop`, `python-patterns` rules).

## Out of scope (for now)

- Committing/pushing without explicit user request
- Choosing frontend framework before requirements are set
- Implementing full worker agent or gateway UI before backend models are defined
