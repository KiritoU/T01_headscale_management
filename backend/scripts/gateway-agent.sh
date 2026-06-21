#!/usr/bin/env bash
# Gateway agent install script (core only) — enrolls via token and starts polling daemon.
#
# Remote install (one-liner — token and URL injected by control plane when fetched with ?token=):
#   curl -fsSL "${CONTROL_PLANE_URL}/gateway-agent.sh?token=TOKEN" | bash
set -euo pipefail

CONTROL_PLANE_URL="${CONTROL_PLANE_URL:-}"
ENROLL_TOKEN="${ENROLL_TOKEN:-}"
INSTALL_DIR="${INSTALL_DIR:-/opt/headscale-gateway-agent}"
SERVICE_NAME="${SERVICE_NAME:-headscale-gateway-agent}"

if [[ -z "${CONTROL_PLANE_URL}" && -n "${INSTALL_FROM_URL:-}" ]]; then
  CONTROL_PLANE_URL="$(printf '%s' "${INSTALL_FROM_URL}" | sed -E 's#(https?://[^/?#]+).*#\1#')"
fi

if [[ -z "${ENROLL_TOKEN}" && -n "${QUERY_STRING:-}" ]]; then
  ENROLL_TOKEN="$(printf '%s' "${QUERY_STRING}" | sed -n 's/.*[?&]token=\([^&]*\).*/\1/p')"
fi

if [[ -z "${ENROLL_TOKEN}" ]]; then
  echo "ENROLL_TOKEN is required (env ENROLL_TOKEN or ?token= query)" >&2
  exit 1
fi

if [[ -z "${CONTROL_PLANE_URL}" ]]; then
  echo "CONTROL_PLANE_URL is required (set by control plane install script or env)" >&2
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
  BUNDLE_URL="${CONTROL_PLANE_URL%/}/api/workers/agent-daemon-bundle.tar.gz"
  TMP_BUNDLE="$(mktemp)"
  if ! curl -fsSL "${BUNDLE_URL}" -o "${TMP_BUNDLE}"; then
    echo "Failed to download agent bundle from ${BUNDLE_URL}" >&2
    echo "Ensure the control plane is reachable and /api/workers/agent-daemon-bundle.tar.gz is available." >&2
    rm -f "${TMP_BUNDLE}"
    exit 1
  fi
  tar -xzf "${TMP_BUNDLE}" -C "${INSTALL_DIR}"
  rm -f "${TMP_BUNDLE}"
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
POLL_INTERVAL=${POLL_INTERVAL:-15}
EOF
chmod 600 "${INSTALL_DIR}/gateway-agent.env"

if command -v systemctl >/dev/null 2>&1 && [[ "$(id -u)" -eq 0 ]]; then
  INSTALL_SYSTEMD="${SCRIPT_DIR}/install-gateway-agent-systemd.sh"
  if [[ ! -x "${INSTALL_SYSTEMD}" ]]; then
    chmod +x "${INSTALL_SYSTEMD}"
  fi
  "${INSTALL_SYSTEMD}" \
    --install-dir "${INSTALL_DIR}" \
    --runner "${RUNNER}" \
    --env-file "${INSTALL_DIR}/gateway-agent.env" \
    --template "${UNIT_TEMPLATE:-${SCRIPT_DIR}/gateway-agent.service.template}" \
    --service-name "${SERVICE_NAME}"
  echo "Gateway agent enrolled (${AGENT_ID}) and service ${SERVICE_NAME} enabled on boot."
else
  echo "Gateway agent enrolled (${AGENT_ID}). Install systemd service as root:"
  echo "  sudo ${SCRIPT_DIR}/install-gateway-agent-systemd.sh \\"
  echo "    --install-dir ${INSTALL_DIR} \\"
  echo "    --runner ${RUNNER} \\"
  echo "    --env-file ${INSTALL_DIR}/gateway-agent.env"
  echo "Or start manually:"
  echo "  set -a && source ${INSTALL_DIR}/gateway-agent.env && set +a"
  echo "  PYTHONPATH=${INSTALL_DIR} ${RUNNER} -m agent_daemon.gateway_daemon"
fi
