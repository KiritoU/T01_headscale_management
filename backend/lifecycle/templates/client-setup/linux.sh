#!/bin/sh
# Tailscale install/connect script (prompt auth key at runtime)
# Safe for piped execution such as:
#   curl -fsSL https://mydomain.com/script.sh | sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Optional Headscale login server
LOGIN_SERVER="https://headscale.ovncr.vn"

# Runtime auth key (prompted)
AUTH_KEY=""

# Max time to wait for `tailscale up` to reach a Running state before giving up.
# Without a bound, `tailscale up` blocks forever when the node cannot reach the
# login server, which looks like the script "hanging".
TAILSCALE_UP_TIMEOUT="${TAILSCALE_UP_TIMEOUT:-60s}"

read_user_input() {
    prompt_text="$1"

    if [ -r /dev/tty ]; then
        printf "%s" "$prompt_text" > /dev/tty
        if IFS= read -r REPLY < /dev/tty; then
            return 0
        fi
        return 1
    fi

    # Fallback for non-piped execution
    printf "%s" "$prompt_text"
    if IFS= read -r REPLY; then
        return 0
    fi
    return 1
}

log_info() {
    printf "${GREEN}[INFO]${NC} %s\n" "$1"
}

log_warn() {
    printf "${YELLOW}[WARN]${NC} %s\n" "$1"
}

log_error() {
    printf "${RED}[ERROR]${NC} %s\n" "$1"
}

check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        log_error "This script must be run as root or with sudo"
        exit 1
    fi
}

detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        DISTRO=$ID
        VERSION=$VERSION_ID
    else
        log_error "Cannot detect Linux distribution. /etc/os-release not found."
        exit 1
    fi

    log_info "Detected distribution: $DISTRO $VERSION"
}

is_tailscale_installed() {
    if command -v tailscale >/dev/null 2>&1; then
        return 0
    fi

    if systemctl list-unit-files 2>/dev/null | grep -q "^tailscaled.service"; then
        if [ -f /etc/systemd/system/tailscaled.service ] || [ -f /usr/lib/systemd/system/tailscaled.service ] || [ -f /lib/systemd/system/tailscaled.service ]; then
            return 0
        fi
    fi

    return 1
}

install_tailscale() {
    log_info "Installing Tailscale..."

    case $DISTRO in
        ubuntu|debian|kali)
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq
            apt-get install -y -qq curl gnupg
            curl -fsSL https://tailscale.com/install.sh | sh
            ;;
        rhel|centos|fedora|rocky|almalinux)
            if command -v dnf >/dev/null 2>&1; then
                dnf install -y curl
                curl -fsSL https://tailscale.com/install.sh | sh
            elif command -v yum >/dev/null 2>&1; then
                yum install -y curl
                curl -fsSL https://tailscale.com/install.sh | sh
            else
                log_error "Neither dnf nor yum found"
                exit 1
            fi
            ;;
        arch|manjaro)
            pacman -Sy --noconfirm curl
            curl -fsSL https://tailscale.com/install.sh | sh
            ;;
        *)
            log_error "Unsupported distribution: $DISTRO"
            log_info "Please install Tailscale manually from https://tailscale.com/download"
            exit 1
            ;;
    esac

    log_info "Tailscale installation completed"
}

setup_service() {
    log_info "Setting up Tailscale service..."

    if ! systemctl list-unit-files 2>/dev/null | grep -q "^tailscaled.service"; then
        log_error "tailscaled service not found. Tailscale may not be installed correctly."
        install_tailscale
        systemctl daemon-reload
        sleep 2
    fi

    systemctl enable tailscaled >/dev/null 2>&1 || true
    systemctl start tailscaled >/dev/null 2>&1 || true

    sleep 2
    if systemctl is-active --quiet tailscaled 2>/dev/null; then
        log_info "Tailscale service is running"
    else
        log_error "Tailscale service failed to start"
        systemctl status tailscaled || true
        exit 1
    fi
}

validate_login_server() {
    if [ -z "$LOGIN_SERVER" ]; then
        log_info "No custom login server specified, will use default Tailscale server"
        return 0
    fi

    if ! echo "$LOGIN_SERVER" | grep -qE "^https?://"; then
        log_error "Invalid login server URL format. URL should start with http:// or https://"
        exit 1
    fi
}

prompt_auth_key() {
    while true; do
        if ! read_user_input "Nhap auth key Headscale/Tailscale: "; then
            log_error "Khong the doc auth key tu nguoi dung."
            log_error "Neu chay qua pipe, hay dam bao /dev/tty kha dung."
            exit 1
        fi

        AUTH_KEY="$(echo "$REPLY" | tr -d '[:space:]')"
        if [ -z "$AUTH_KEY" ]; then
            log_warn "Auth key khong duoc de trong. Vui long nhap lai."
            continue
        fi
        break
    done
}

disconnect_tailscale() {
    log_info "Checking current Tailscale connection status..."
    if tailscale status >/dev/null 2>&1; then
        status_output="$(tailscale status 2>/dev/null | sed -n '1p')"
        if [ -n "$status_output" ] && echo "$status_output" | grep -qE "^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+"; then
            log_warn "Tailscale is already connected. Disconnecting to switch account..."
            tailscale down || true
            sleep 2

            log_info "Removing Tailscale state to fully reset connection..."
            rm -f /var/lib/tailscale/tailscaled.state
            systemctl restart tailscaled
            sleep 3
        fi
    fi
}

check_login_server_reachable() {
    # Best-effort probe so we can warn early instead of silently hanging in
    # `tailscale up`. Network paths can differ, so a failure here only warns.
    if [ -z "$LOGIN_SERVER" ]; then
        return 0
    fi
    if ! command -v curl >/dev/null 2>&1; then
        return 0
    fi
    log_info "Probing login server $LOGIN_SERVER ..."
    code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "$LOGIN_SERVER" 2>/dev/null || echo 000)"
    if [ "$code" = "000" ]; then
        log_warn "Could not reach $LOGIN_SERVER (no HTTP response)."
        log_warn "If the next step hangs, check DNS, firewall, and TLS to the headscale host."
    else
        log_info "Login server responded (HTTP $code)."
    fi
}

connect_tailscale() {
    log_info "Connecting to Tailscale..."
    disconnect_tailscale
    check_login_server_reachable

    log_info "Bringing Tailscale up (timeout ${TAILSCALE_UP_TIMEOUT})..."
    up_rc=0
    if [ -n "$LOGIN_SERVER" ]; then
        tailscale up \
            --timeout="$TAILSCALE_UP_TIMEOUT" \
            --force-reauth \
            --login-server="$LOGIN_SERVER" \
            --authkey="$AUTH_KEY" \
            --accept-routes \
            --accept-dns || up_rc=$?
    else
        tailscale up \
            --timeout="$TAILSCALE_UP_TIMEOUT" \
            --force-reauth \
            --authkey="$AUTH_KEY" \
            --accept-routes \
            --accept-dns || up_rc=$?
    fi

    if [ "$up_rc" -ne 0 ]; then
        log_error "tailscale up did not reach Running within ${TAILSCALE_UP_TIMEOUT} (exit ${up_rc})."
        log_warn "Current status:"
        tailscale status || true
        log_warn "Troubleshooting:"
        log_warn "  1. Confirm ${LOGIN_SERVER} is reachable from this machine."
        log_warn "  2. tailscaled keeps retrying in the background; re-run this script to retry."
        exit "$up_rc"
    fi

    log_info "Successfully connected to Tailscale!"
    tailscale status || true
}

main() {
    log_info "Starting Tailscale setup (prompt auth key mode)..."

    check_root
    detect_distro

    if is_tailscale_installed; then
        log_info "Tailscale is already installed"
    else
        install_tailscale
    fi

    setup_service
    validate_login_server
    prompt_auth_key
    connect_tailscale

    log_info "All done."
}

main
