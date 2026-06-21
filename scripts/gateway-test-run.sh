#!/usr/bin/env bash
# Enroll (if needed) and install a local gateway agent as a systemd service.
set -euo pipefail

CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://127.0.0.1:8000}"
TENANT_ID="${TENANT_ID:-}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
GATEWAY_HOSTNAME="${GATEWAY_HOSTNAME:-$(hostname -s 2>/dev/null || hostname)}"
SERVICE_NAME="${SERVICE_NAME:-headscale-gateway-agent}"
BACKEND_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../backend" && pwd)"
ENV_FILE="${ENV_FILE:-${BACKEND_ROOT}/.gateway-agent.env}"
INSTALL_SCRIPT="${BACKEND_ROOT}/scripts/install-gateway-agent-systemd.sh"

if [[ ! -f "${ENV_FILE}" && -f /tmp/gateway-test.env ]]; then
  echo "Migrating credentials from /tmp/gateway-test.env..." >&2
  cp /tmp/gateway-test.env "${ENV_FILE}"
  chmod 600 "${ENV_FILE}"
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  if [[ -z "${TENANT_ID}" ]]; then
    echo "Fetching first tenant id from ${CONTROL_PLANE_URL}..." >&2
    TENANT_ID="$(curl -fsS "${CONTROL_PLANE_URL}/api/tenants/" | python3 -c "
import json, sys
body = json.load(sys.stdin)
items = body if isinstance(body, list) else body.get('data') or []
print(items[0]['id'] if items else '')
")"
  fi

  if [[ -z "${TENANT_ID}" ]]; then
    echo "No tenant found. Create a tenant first." >&2
    exit 1
  fi

  echo "Creating enrollment token for tenant ${TENANT_ID}..." >&2
  TOKEN_RESPONSE="$(curl -fsS \
    -X POST "${CONTROL_PLANE_URL}/api/tenants/${TENANT_ID}/gateways/enrollment-tokens/" \
    -H "Content-Type: application/json" \
    -d '{"max_uses": 5}')"
  ENROLL_TOKEN="$(printf '%s' "${TOKEN_RESPONSE}" | python3 -c "
import json, sys
body = json.load(sys.stdin)
print(body['data']['token'])
")"

  REGISTER_PAYLOAD="$(printf '{"agent_type":"gateway","enrollment_token":"%s","hostname":"%s"}' \
    "${ENROLL_TOKEN}" "${GATEWAY_HOSTNAME}")"

  REGISTER_RESPONSE="$(curl -fsS \
    -X POST "${CONTROL_PLANE_URL}/api/v1/agents/register/" \
    -H "Content-Type: application/json" \
    -d "${REGISTER_PAYLOAD}")"

  AGENT_ID="$(printf '%s' "${REGISTER_RESPONSE}" | python3 -c "
import json, sys
print(json.load(sys.stdin)['agent_id'])
")"
  AGENT_TOKEN="$(printf '%s' "${REGISTER_RESPONSE}" | python3 -c "
import json, sys
print(json.load(sys.stdin)['token'])
")"

  cat > "${ENV_FILE}" <<EOF
CONTROL_PLANE_URL=${CONTROL_PLANE_URL}
AGENT_ID=${AGENT_ID}
AGENT_TOKEN=${AGENT_TOKEN}
POLL_INTERVAL=${POLL_INTERVAL}
EOF
  chmod 600 "${ENV_FILE}"
  echo "Enrolled gateway agent ${AGENT_ID} (hostname ${GATEWAY_HOSTNAME})" >&2
  echo "Credentials saved to ${ENV_FILE}" >&2
else
  # Keep poll interval / control plane URL in sync when re-running the script.
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  cat > "${ENV_FILE}" <<EOF
CONTROL_PLANE_URL=${CONTROL_PLANE_URL}
AGENT_ID=${AGENT_ID}
AGENT_TOKEN=${AGENT_TOKEN}
POLL_INTERVAL=${POLL_INTERVAL}
EOF
  chmod 600 "${ENV_FILE}"
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Re-run as root to install systemd service (auto-start on boot):" >&2
  echo "  sudo $0" >&2
  exit 1
fi

if [[ ! -d "${BACKEND_ROOT}/.venv" ]]; then
  echo "Creating backend virtualenv..." >&2
  (cd "${BACKEND_ROOT}" && uv sync --quiet)
fi

RUNNER="${BACKEND_ROOT}/.venv/bin/python"
if [[ ! -x "${RUNNER}" ]]; then
  echo "Python runner not found: ${RUNNER}" >&2
  exit 1
fi

chmod +x "${INSTALL_SCRIPT}"
"${INSTALL_SCRIPT}" \
  --install-dir "${BACKEND_ROOT}" \
  --runner "${RUNNER}" \
  --env-file "${ENV_FILE}" \
  --service-name "${SERVICE_NAME}"

echo "Gateway agent ${SERVICE_NAME} is enabled — survives reboot." >&2
