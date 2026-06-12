# uv dependency quick reference

## Add

```bash
uv add httpx
uv add "httpx>=0.27"
uv add --dev pytest
uv add --group lint ruff
uv add -r requirements.txt          # migrate from requirements.txt
```

## Remove

```bash
uv remove httpx
uv remove pytest --dev
uv remove ruff --group lint
```

## Sync environment

```bash
uv sync
uv sync --frozen          # CI: do not update lockfile
uv sync --no-dev          # production-like install
uv sync --all-groups
```

## Run without activating venv

```bash
uv run python script.py
uv run pytest
uv run django-admin startapp myapp
```

## Lock / export

```bash
uv lock
uv export --format requirements-txt > requirements.txt   # only if explicitly needed
```
