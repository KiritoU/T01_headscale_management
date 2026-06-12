---
name: uv-python-backend
description: >-
  Python backend development with uv for headscale-management. Use when adding
  or removing dependencies, scaffolding Django/apps, running migrations, tests,
  or any backend Python work in backend/.
---

# uv Python Backend

## Non-negotiable rules

### 1. Manage dependencies only with uv

```bash
# Add runtime dependency
uv add requests

# Add with version constraint
uv add "django>=5.0"

# Add dev / group dependency
uv add --dev pytest
uv add --group lint ruff

# Remove
uv remove requests
uv remove pytest --dev
```

**Never**:
- `pip install` / `pip uninstall`
- Manually append packages to `pyproject.toml` or `uv.lock`
- `poetry add` / `pipenv` / other package managers

Changing a version constraint: `uv add "package>=x.y"` (optionally `--upgrade-package package`).

### 2. Prefer official CLI over hand-written boilerplate

Before creating apps, migrations, or framework files manually, run the tool's generator:

| Task | Command |
|------|---------|
| New Django app | `uv run django-admin startapp <name>` |
| Migrations | `uv run python manage.py makemigrations` |
| Apply migrations | `uv run python manage.py migrate` |
| Django project (once) | `uv run django-admin startproject <name> .` |
| Generic script | `uv run python script.py` |
| Tests | `uv run pytest` |

If a library documents a scaffold command, **use it first**. Only hand-write files when no generator exists or the generator cannot express the need.

### 3. Run everything through uv

```bash
uv run python manage.py runserver
uv run python -m mymodule
uv sync                    # align .venv with lockfile
uv sync --group test       # install specific dependency group
```

## Project bootstrap (when backend/ is empty)

From repository root:

```bash
mkdir -p backend && cd backend
uv init
# then add framework, e.g.:
uv add django djangorestframework
uv run django-admin startproject config .
```

Do not copy `pyproject.toml` templates from other projects without `uv init` / `uv add`.

## pyproject.toml edits

Allowed manual edits: project metadata, tool config (`[tool.ruff]`, `[tool.pytest.ini_options]`, Django settings paths).

**Not allowed manually**: `[project].dependencies`, `[dependency-groups]`, optional deps — use `uv add` / `uv remove`.

## Common checks before finishing backend work

```bash
cd backend
uv sync
uv run python manage.py check    # if Django
uv run pytest                    # if tests exist
```

## Additional resources

- uv dependency reference: [uv-dependencies.md](uv-dependencies.md)
