#!/usr/bin/env bash
set -euo pipefail

# DataTalk Events - Hetzner Cloud Deploy Script
# Prerequisites: hcloud CLI, HCLOUD_TOKEN env var, ssh-keygen

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
export PROJECT_ROOT

# Configuration - all from environment
SERVER_NAME="${SERVER_NAME:-datatalk-events}"
SERVER_TYPE="${SERVER_TYPE:-cax11}"
SERVER_LOCATION="${SERVER_LOCATION:-nbg1}"
SERVER_IMAGE="${SERVER_IMAGE:-ubuntu-24.04}"
SSH_KEY_NAME="${SSH_KEY_NAME:-datatalk-events}"
FIREWALL_NAME="${FIREWALL_NAME:-datatalk-events}"
DOMAIN="${DOMAIN:-}"  # Required for HTTPS

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# Check prerequisites
command -v hcloud >/dev/null 2>&1 || error "hcloud CLI not found. Install: brew install hcloud"
[[ -n "${HCLOUD_TOKEN:-}" ]] || error "HCLOUD_TOKEN not set"

# 1. SSH Key
info "Setting up SSH key..."
if ! hcloud ssh-key describe "$SSH_KEY_NAME" >/dev/null 2>&1; then
    if [[ ! -f ~/.ssh/id_ed25519.pub ]]; then
        ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N "" -q
    fi
    hcloud ssh-key create --name "$SSH_KEY_NAME" --public-key-from-file ~/.ssh/id_ed25519.pub
    info "SSH key '$SSH_KEY_NAME' created"
else
    info "SSH key '$SSH_KEY_NAME' already exists"
fi

# 2. Firewall
info "Setting up firewall..."
if ! hcloud firewall describe "$FIREWALL_NAME" >/dev/null 2>&1; then
    hcloud firewall create --name "$FIREWALL_NAME"
    hcloud firewall add-rule "$FIREWALL_NAME" --direction in --protocol tcp --port 22 --source-ips 0.0.0.0/0 --source-ips ::/0 --description "SSH"
    hcloud firewall add-rule "$FIREWALL_NAME" --direction in --protocol tcp --port 80 --source-ips 0.0.0.0/0 --source-ips ::/0 --description "HTTP"
    hcloud firewall add-rule "$FIREWALL_NAME" --direction in --protocol tcp --port 443 --source-ips 0.0.0.0/0 --source-ips ::/0 --description "HTTPS"
    info "Firewall '$FIREWALL_NAME' created with rules for ports 22, 80, 443"
else
    info "Firewall '$FIREWALL_NAME' already exists"
fi

# 3. Cloud-init
info "Preparing cloud-init..."
CLOUD_INIT=$(envsubst < "$SCRIPT_DIR/cloud-init.yml")

# 4. Create server
info "Creating server '$SERVER_NAME'..."
if hcloud server describe "$SERVER_NAME" >/dev/null 2>&1; then
    warn "Server '$SERVER_NAME' already exists. Delete it first or use a different name."
    exit 1
fi

hcloud server create \
    --name "$SERVER_NAME" \
    --type "$SERVER_TYPE" \
    --location "$SERVER_LOCATION" \
    --image "$SERVER_IMAGE" \
    --ssh-key "$SSH_KEY_NAME" \
    --firewall "$FIREWALL_NAME" \
    --user-data-from-file <(echo "$CLOUD_INIT")

# 5. Get server IP
SERVER_IP=$(hcloud server ip "$SERVER_NAME")
info "Server created: $SERVER_IP"

# 6. Wait for cloud-init
info "Waiting for cloud-init to complete (this may take 3-5 minutes)..."
for _ in $(seq 1 60); do
    if ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 root@"$SERVER_IP" 'cloud-init status --wait' 2>/dev/null | grep -q 'done'; then
        break
    fi
    sleep 10
done

info "===================="
info "Deployment complete!"
info "===================="
info "Server IP: $SERVER_IP"
info "SSH: ssh root@$SERVER_IP"
if [[ -n "$DOMAIN" ]]; then
    info "URL: https://$DOMAIN"
    info ""
    info "NEXT: Point your DNS A record for $DOMAIN to $SERVER_IP"
else
    info "URL: http://$SERVER_IP:8000"
    info ""
    warn "No DOMAIN set. Set DOMAIN env var for HTTPS with Caddy."
fi
info "Health: curl http://$SERVER_IP:8000/health"
