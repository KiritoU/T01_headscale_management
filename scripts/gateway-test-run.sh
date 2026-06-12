#!/usr/bin/env bash
# Run a local gateway-test agent against the control plane on this machine.
set -euo pipefail

CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-http://127.0.0.1:8000}"
TENANT_ID="${TENANT_ID:-}"
POLL_INTERVAL="${POLL_INTERVAL:-10}"
BACKEND_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../backend" && pwd)"
ENV_FILE="${ENV_FILE:-/tmp/gateway-test.env}"

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

if [[ ! -f "${ENV_FILE}" ]]; then
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

  HOSTNAME="$(hostname -s 2>/dev/null || hostname)"
  REGISTER_PAYLOAD="$(printf '{"agent_type":"gateway","enrollment_token":"%s","hostname":"%s"}' \
    "${ENROLL_TOKEN}" "gateway-test-${HOSTNAME}")"

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
  echo "Enrolled gateway-test agent ${AGENT_ID}" >&2
  echo "Credentials saved to ${ENV_FILE}" >&2
fi

# shellcheck disable=SC1090
source "${ENV_FILE}"

echo "Starting gateway-test daemon (poll every ${POLL_INTERVAL}s)..." >&2
cd "${BACKEND_ROOT}"
exec uv run python -m agent_daemon.gateway_daemon \
  --control-plane "${CONTROL_PLANE_URL}" \
  --agent-id "${AGENT_ID}" \
  --token "${AGENT_TOKEN}" \
  --poll-interval "${POLL_INTERVAL}"
