#!/bin/sh
# Tailscale Gateway Setup Script for Linux
# This script installs Tailscale (if needed), then configures this VM as a subnet router (gateway)
# with user-provided advertised routes.
# Usage: sudo ./gateway.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Default settings (can be edited directly in this file)
LOGIN_SERVER="https://headscale.ovncr.vn"
AUTH_KEY=""

# Max time to wait for `tailscale up` to reach a Running state before giving up.
# Without a bound, `tailscale up` blocks forever when the node cannot reach the
# login server, which looks like the script "hanging".
TAILSCALE_UP_TIMEOUT="${TAILSCALE_UP_TIMEOUT:-60s}"

# Global variable to hold final comma-separated routes
ADVERTISE_ROUTES=""

read_user_input() {
    prompt_text="$1"

    if [ -r /dev/tty ]; then
        printf "%s" "$prompt_text" > /dev/tty
        if IFS= read -r REPLY < /dev/tty; then
            return 0
        fi
        return 1
    fi

    # Fallback for direct script execution (not piped)
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
        if ! read_user_input "Nhap auth key: "; then
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

validate_cidr() {
    cidr="$1"
    ip=""
    prefix=""

    if ! echo "$cidr" | grep -qE '^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$'; then
        return 1
    fi

    ip="${cidr%/*}"
    prefix="${cidr#*/}"

    if [ "$prefix" -lt 0 ] || [ "$prefix" -gt 32 ]; then
        return 1
    fi

    old_ifs="$IFS"
    IFS='.'
    set -- $ip
    IFS="$old_ifs"

    for octet in "$1" "$2" "$3" "$4"; do
        if [ -z "$octet" ] || [ "$octet" -lt 0 ] || [ "$octet" -gt 255 ]; then
            return 1
        fi
    done

    return 0
}

collect_advertise_routes() {
    raw_input=""
    item=""
    cleaned_item=""
    routes_csv=""

    log_info "Gateway route setup"
    printf "\n"
    printf "Nhap tat ca subnet can advertise (CIDR) tren 1 dong, cach nhau boi dau phay ','\n"
    printf "Vi du: 192.168.101.0/24,192.168.102.0/24\n"
    printf "\n"

    while true; do
        routes_csv=""
        all_valid=true

        if ! read_user_input "Nhap danh sach subnet: "; then
            log_error "Khong the doc input tu nguoi dung."
            log_error "Neu chay qua pipe, hay dam bao /dev/tty kha dung."
            exit 1
        fi
        raw_input="$REPLY"

        raw_input="$(echo "$raw_input" | tr -d '[:space:]')"
        if [ -z "$raw_input" ]; then
            log_warn "Ban chua nhap subnet nao. Vui long thu lai."
            continue
        fi

        old_ifs="$IFS"
        IFS=','
        set -- $raw_input
        IFS="$old_ifs"

        for item in "$@"; do
            cleaned_item="$(echo "$item" | tr -d '[:space:]')"
            if [ -z "$cleaned_item" ]; then
                continue
            fi

            if ! validate_cidr "$cleaned_item"; then
                log_error "Subnet khong hop le: $cleaned_item"
                all_valid=false
            else
                if [ -n "$routes_csv" ]; then
                    routes_csv="${routes_csv},${cleaned_item}"
                else
                    routes_csv="$cleaned_item"
                fi
            fi
        done

        if [ -z "$routes_csv" ]; then
            log_warn "Khong co subnet hop le. Vui long nhap lai."
            continue
        fi

        if [ "$all_valid" != true ]; then
            log_warn "Co subnet khong hop le. Vui long nhap lai."
            continue
        fi

        ADVERTISE_ROUTES="$routes_csv"
        log_info "Subnets se advertise: $ADVERTISE_ROUTES"

        if ! read_user_input "Xac nhan danh sach nay? (y/n): "; then
            log_error "Khong the doc input tu nguoi dung."
            exit 1
        fi
        confirm="$REPLY"
        case "$confirm" in
            y|Y|yes|YES)
                break
                ;;
            *)
                log_info "Nhap lai danh sach subnet..."
                ;;
        esac
    done
}

enable_ip_forwarding() {
    log_info "Enabling IPv4 forwarding..."
    if [ -f /etc/sysctl.conf ] && ! grep -qE "^[[:space:]]*net\.ipv4\.ip_forward[[:space:]]*=[[:space:]]*1[[:space:]]*$" /etc/sysctl.conf 2>/dev/null; then
        echo "" >> /etc/sysctl.conf
        echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
    fi

    sysctl -w net.ipv4.ip_forward=1 >/dev/null
    sysctl -p >/dev/null 2>&1 || true
    log_info "IPv4 forwarding enabled"
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

connect_as_gateway() {
    log_info "Configuring this VM as subnet gateway..."
    check_login_server_reachable

    # Omit --accept-routes on the subnet router: it only pulls in *other* tailnet routes and can
    # conflict with local LAN routing. Clients that should reach advertised subnets must run
    # tailscale up/set with --accept-routes themselves.

    log_info "Bringing Tailscale up (timeout ${TAILSCALE_UP_TIMEOUT})..."
    up_rc=0
    if [ -n "$LOGIN_SERVER" ]; then
        tailscale up \
            --timeout="$TAILSCALE_UP_TIMEOUT" \
            --force-reauth \
            --login-server="$LOGIN_SERVER" \
            --authkey="$AUTH_KEY" \
            --advertise-routes="$ADVERTISE_ROUTES" \
            --accept-dns \
            --reset || up_rc=$?
    else
        tailscale up \
            --timeout="$TAILSCALE_UP_TIMEOUT" \
            --force-reauth \
            --authkey="$AUTH_KEY" \
            --advertise-routes="$ADVERTISE_ROUTES" \
            --accept-dns \
            --reset || up_rc=$?
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

    log_info "Gateway setup completed. Current Tailscale status:"
    tailscale status || true
}

main() {
    log_info "Starting Tailscale gateway setup..."
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
    collect_advertise_routes
    enable_ip_forwarding
    connect_as_gateway

    log_info "All done."
}

main
