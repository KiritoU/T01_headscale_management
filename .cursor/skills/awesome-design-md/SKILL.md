---
name: awesome-design-md
description: >-
  Applies the project DESIGN.md visual system (Supabase-inspired, dark emerald
  dev-dashboard) for consistent UI. Use when building frontend pages,
  components, styling, or when the user asks for design consistency, colors,
  typography, or component patterns.
---

# awesome-design-md

## Visual source of truth

**Primary:** `DESIGN.md` at project root (from [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md) — `supabase` style).

Chosen for headscale-management because it matches an **infrastructure admin dashboard**: dark surfaces, emerald accent, code-first density, data tables, status indicators.

## When building UI

1. **Read `DESIGN.md` first** — colors, typography, components, layout, do's/don'ts.
2. Use **ui-ux-pro-max** skill for UX rules, stack guidance, accessibility checklist.
3. Use **`design-system/headscale-management/MASTER.md`** for page-level overrides only.

**Priority:** `design-system/pages/<page>.md` → `DESIGN.md` → `MASTER.md`

## Key tokens (quick reference)

| Token | Value | Use |
|-------|-------|-----|
| Primary | `#3ecf8e` | CTAs, active states, success |
| Canvas night | `#1c1c1c` | App background (dark mode) |
| Ink | `#171717` | Primary text on light |
| On-dark | `#ffffff` | Text on dark surfaces |

Full palette and component specs are in `DESIGN.md`.

## Prompt pattern

```
Build [page/component]. Follow DESIGN.md for colors, typography, and components.
Use dark mode default. Stack: [React + Tailwind / chosen stack].
Apply ui-ux-pro-max accessibility checklist before finishing.
```

## Swap design style

To change the visual language, replace `DESIGN.md` with another from awesome-design-md:

| Style | Site slug | Best for |
|-------|-----------|----------|
| Current | `supabase` | Infra admin, dark emerald |
| Alt | `posthog` | Playful dev analytics |
| Alt | `sentry` | Error/ops monitoring, pink accent |
| Alt | `linear.app` | Ultra-minimal purple |
| Alt | `vercel` | Monochrome Geist precision |

Download: `https://raw.githubusercontent.com/VoltAgent/awesome-design-md/main/design-md/<slug>/DESIGN.md`

## Additional resources

- Catalog: [VoltAgent/awesome-design-md](https://github.com/VoltAgent/awesome-design-md)
- UX workflow: [ui-ux-pro-max](../ui-ux-pro-max/SKILL.md)
