#!/bin/sh
set -eu

echo "Running database migrations..."
uv run python manage.py migrate --noinput

echo "Collecting static files..."
uv run python manage.py collectstatic --noinput --clear

if [ -n "${ADMIN_PASSWORD:-}" ]; then
  echo "Ensuring admin user exists..."
  if ! uv run python manage.py seed_admin; then
    echo "Admin user already exists (set ADMIN_PASSWORD and run seed_admin --force to reset)."
  fi
fi

exec "$@"
