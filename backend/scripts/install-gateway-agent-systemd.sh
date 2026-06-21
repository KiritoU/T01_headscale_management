#!/usr/bin/env bash
# Install or refresh the systemd unit for a gateway agent daemon.
set -euo pipefail

SERVICE_NAME="${SERVICE_NAME:-headscale-gateway-agent}"
INSTALL_DIR=""
RUNNER=""
ENV_FILE=""
UNIT_TEMPLATE=""

usage() {
  cat <<EOF
Usage: install-gateway-agent-systemd.sh --install-dir DIR --runner PATH --env-file PATH

Options:
  --install-dir DIR   Working directory (agent code + PYTHONPATH root)
  --runner PATH       Python interpreter (venv) to run gateway_daemon
  --env-file PATH     Environment file with CONTROL_PLANE_URL, AGENT_ID, AGENT_TOKEN
  --template PATH     Optional systemd unit template
  --service-name NAME Systemd unit name (default: headscale-gateway-agent)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir)
      INSTALL_DIR="$2"
      shift 2
      ;;
    --runner)
      RUNNER="$2"
      shift 2
      ;;
    --env-file)
      ENV_FILE="$2"
      shift 2
      ;;
    --template)
      UNIT_TEMPLATE="$2"
      shift 2
      ;;
    --service-name)
      SERVICE_NAME="$2"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [[ -z "${INSTALL_DIR}" || -z "${RUNNER}" || -z "${ENV_FILE}" ]]; then
  echo "Missing required arguments." >&2
  usage >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Environment file not found: ${ENV_FILE}" >&2
  exit 1
fi

if [[ ! -x "${RUNNER}" ]]; then
  echo "Runner not executable: ${RUNNER}" >&2
  exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "systemctl not found; cannot install gateway agent service." >&2
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run as root to install systemd service (sudo $0 ...)." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "${UNIT_TEMPLATE}" ]]; then
  UNIT_TEMPLATE="${SCRIPT_DIR}/gateway-agent.service.template"
fi

UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ -f "${UNIT_TEMPLATE}" ]]; then
  sed \
    -e "s|@INSTALL_DIR@|${INSTALL_DIR}|g" \
    -e "s|@SERVICE_NAME@|${SERVICE_NAME}|g" \
    -e "s|@RUNNER@|${RUNNER}|g" \
    -e "s|@ENV_FILE@|${ENV_FILE}|g" \
    "${UNIT_TEMPLATE}" > "${UNIT_PATH}"
else
  cat > "${UNIT_PATH}" <<EOF
[Unit]
Description=Headscale Gateway Agent (${SERVICE_NAME})
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
EnvironmentFile=${ENV_FILE}
Environment=PYTHONPATH=${INSTALL_DIR}
WorkingDirectory=${INSTALL_DIR}
ExecStart=${RUNNER} -m agent_daemon.gateway_daemon
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
fi

# Stop ad-hoc daemons started outside systemd before handoff.
pkill -f "agent_daemon.gateway_daemon" 2>/dev/null || true
sleep 1

systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"
systemctl restart "${SERVICE_NAME}"

echo "Gateway agent systemd service installed: ${SERVICE_NAME}"
systemctl --no-pager --full status "${SERVICE_NAME}" || true
