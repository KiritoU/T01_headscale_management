#!/usr/bin/env bash
# Gateway agent install script (core only) — enrolls via token and starts polling daemon.
#
# Remote install:
#   curl -fsSL "${CONTROL_PLANE_URL}/gateway-agent.sh?token=TOKEN" \
#     | CONTROL_PLANE_URL="${CONTROL_PLANE_URL}" ENROLL_TOKEN="TOKEN" bash
#
# CONTROL_PLANE_URL — API base URL (must reach /api/v1/agents/register/).
#   Dev (Vite :5173): same origin as the script URL works; Vite proxies /api to Django :8000.
#   Production: use the Django/nginx host (e.g. https://control.example.com or http://host:8000).
# Optional INSTALL_FROM_URL — when CONTROL_PLANE_URL is unset, derive origin from the curl URL.
set -euo pipefail

CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-}"
ENROLL_TOKEN="${ENROLL_TOKEN:-}"
INSTALL_DIR="${INSTALL_DIR:-/opt/headscale-gateway-agent}"
SERVICE_NAME="${SERVICE_NAME:-headscale-gateway-agent}"

if [[ -z "${CONTROL_PLANE_URL}" && -n "${INSTALL_FROM_URL:-}" ]]; then
  CONTROL_PLANE_URL="$(printf '%s' "${INSTALL_FROM_URL}" | sed -E 's#(https?://[^/?#]+).*#\1#')"
fi
CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-https://get.example.com}"

# Parse ?token= from curl URL when piped (best-effort stub via QUERY_STRING env if set)
if [[ -z "${ENROLL_TOKEN}" && -n "${QUERY_STRING:-}" ]]; then
  ENROLL_TOKEN="$(printf '%s' "${QUERY_STRING}" | sed -n 's/.*[?&]token=\([^&]*\).*/\1/p')"
fi

if [[ -z "${ENROLL_TOKEN}" ]]; then
  echo "ENROLL_TOKEN is required (env ENROLL_TOKEN or ?token= query)" >&2
  exit 1
fi

HOSTNAME="$(hostname -s 2>/dev/null || hostname)"

echo "headscale-management gateway agent installer"
echo "Control plane: ${CONTROL_PLANE_URL}"

mkdir -p "${INSTALL_DIR}"

SCRIPT_DIR=""
if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

if [[ -n "${SCRIPT_DIR}" && -d "${SCRIPT_DIR}/../agent_daemon" ]]; then
  cp -r "${SCRIPT_DIR}/../agent_daemon" "${INSTALL_DIR}/"
  if [[ -f "${SCRIPT_DIR}/gateway-agent.service.template" ]]; then
    UNIT_TEMPLATE="${SCRIPT_DIR}/gateway-agent.service.template"
  fi
else
  echo "Downloading agent daemon bundle…"
  curl -fsSL \
    "${CONTROL_PLANE_URL%/}/api/workers/agent-daemon-bundle.tar.gz" \
    | tar -xzf - -C "${INSTALL_DIR}"
  UNIT_TEMPLATE=""
fi

install_agent_python_deps() {
  if command -v uv >/dev/null 2>&1; then
    uv pip install --quiet httpx pyyaml --python "${VENV_DIR}/bin/python"
  else
    "${VENV_DIR}/bin/pip" install --quiet httpx pyyaml
  fi
}

create_agent_venv() {
  if command -v uv >/dev/null 2>&1; then
    uv venv "${VENV_DIR}"
    install_agent_python_deps
    return 0
  fi

  if python3 -m venv "${VENV_DIR}" 2>/dev/null; then
    install_agent_python_deps
    return 0
  fi

  if [[ "$(id -u)" -eq 0 ]] && command -v apt-get >/dev/null 2>&1; then
    echo "Installing python3-venv (required for agent runtime)…"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq python3-venv python3-pip
    python3 -m venv "${VENV_DIR}"
    install_agent_python_deps
    return 0
  fi

  echo "uv or python3-venv is required on the target host" >&2
  echo "On Ubuntu/Debian (as root): apt install python3-venv python3-pip" >&2
  return 1
}

VENV_DIR="${INSTALL_DIR}/.venv"
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "Creating agent virtualenv…"
  create_agent_venv
else
  echo "Updating agent Python dependencies…"
  install_agent_python_deps
fi

RUNNER="${VENV_DIR}/bin/python"
export PYTHONPATH="${INSTALL_DIR}:${PYTHONPATH:-}"

REGISTER_PAYLOAD="$(printf '{"agent_type":"gateway","enrollment_token":"%s","hostname":"%s"}' \
  "${ENROLL_TOKEN}" "${HOSTNAME}")"

REGISTER_RESPONSE="$(curl -fsS \
  -X POST "${CONTROL_PLANE_URL%/}/api/v1/agents/register/" \
  -H "Content-Type: application/json" \
  -d "${REGISTER_PAYLOAD}")"

AGENT_ID="$(printf '%s' "${REGISTER_RESPONSE}" | python3 -c "import sys,json; print(json.load(sys.stdin)['agent_id'])")"
AGENT_TOKEN="$(printf '%s' "${REGISTER_RESPONSE}" | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")"

cat > "${INSTALL_DIR}/gateway-agent.env" <<EOF
CONTROL_PLANE_URL=${CONTROL_PLANE_URL}
AGENT_ID=${AGENT_ID}
AGENT_TOKEN=${AGENT_TOKEN}
EOF
chmod 600 "${INSTALL_DIR}/gateway-agent.env"

if command -v systemctl >/dev/null 2>&1 && [[ "$(id -u)" -eq 0 ]]; then
  UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

  if [[ -n "${UNIT_TEMPLATE:-}" && -f "${UNIT_TEMPLATE}" ]]; then
    sed \
      -e "s|@INSTALL_DIR@|${INSTALL_DIR}|g" \
      -e "s|@SERVICE_NAME@|${SERVICE_NAME}|g" \
      -e "s|@RUNNER@|${RUNNER}|g" \
      "${UNIT_TEMPLATE}" > "${UNIT_PATH}"
  else
    cat > "${UNIT_PATH}" <<EOF
[Unit]
Description=Headscale Gateway Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=${INSTALL_DIR}/gateway-agent.env
Environment=PYTHONPATH=${INSTALL_DIR}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/.venv/bin/python -m agent_daemon.gateway_daemon
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
  fi

  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}"
  systemctl restart "${SERVICE_NAME}"
  echo "Gateway agent enrolled (${AGENT_ID}) and service ${SERVICE_NAME} started."
else
  echo "Gateway agent enrolled (${AGENT_ID}). Start manually:"
  echo "  set -a && source ${INSTALL_DIR}/gateway-agent.env && set +a"
  echo "  PYTHONPATH=${INSTALL_DIR} ${RUNNER} -m agent_daemon.gateway_daemon"
fi
