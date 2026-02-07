# DataTalk Events - Deployment Guide

## Prerequisites

1. **hcloud CLI** - Hetzner Cloud command-line tool
   ```bash
   # macOS
   brew install hcloud

   # Linux
   curl -fsSL https://github.com/hetznercloud/cli/releases/latest/download/hcloud-linux-amd64.tar.gz | tar xz
   sudo mv hcloud /usr/local/bin/
   ```

2. **HCLOUD_TOKEN** - Hetzner Cloud API token
   - Go to https://console.hetzner.cloud/
   - Create a project (or select an existing one)
   - Go to Security > API Tokens > Generate API Token (Read & Write)
   - Export it: `export HCLOUD_TOKEN="your-token-here"`

3. **Domain** (optional, recommended) - For HTTPS via Caddy auto-TLS

## Quick Deploy

```bash
# Required
export HCLOUD_TOKEN="your-hetzner-api-token"

# Required for production
export OPENAI_API_KEY="your-openai-key"
export SECRET_KEY="$(openssl rand -hex 32)"
export ADMIN_PASSWORD="your-strong-password"

# Optional: for HTTPS (recommended)
export DOMAIN="events.yourdomain.com"

# Optional: notification services
export RESEND_API_KEY="your-resend-key"
export TELEGRAM_BOT_TOKEN="your-bot-token"

# Deploy
./deploy/deploy.sh
```

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `SERVER_NAME` | `datatalk-events` | Hetzner server name |
| `SERVER_TYPE` | `cax11` | Server type (ARM, 2 vCPU, 4GB RAM) |
| `SERVER_LOCATION` | `nbg1` | Hetzner datacenter (nbg1, fsn1, hel1) |
| `SERVER_IMAGE` | `ubuntu-24.04` | OS image |
| `SSH_KEY_NAME` | `datatalk-events` | SSH key name in Hetzner |
| `FIREWALL_NAME` | `datatalk-events` | Firewall name in Hetzner |
| `DOMAIN` | *(empty)* | Domain for HTTPS (enables Caddy) |
| `APP_NAME` | `DataTalk Events` | Application display name |
| `DEBUG` | `false` | Debug mode |
| `DATABASE_URL` | `sqlite:///data/app.db` | Database connection string |
| `SCRAPE_URL` | `https://datatalk.cz/kalendar-akci/` | URL to scrape events from |
| `SCRAPE_SCHEDULE` | `0 8 * * 1` | Cron schedule for scraping |
| `OPENAI_API_KEY` | *(empty)* | OpenAI API key for LLM extraction |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model to use |
| `EMAIL_PROVIDER` | `resend` | Email provider (resend or sendgrid) |
| `RESEND_API_KEY` | *(empty)* | Resend API key |
| `SENDGRID_API_KEY` | *(empty)* | SendGrid API key |
| `EMAIL_FROM` | `events@datatalk.cz` | Sender email address |
| `TELEGRAM_BOT_TOKEN` | *(empty)* | Telegram bot token |
| `SECRET_KEY` | *(empty)* | Application secret key |
| `WEBHOOK_URL` | *(empty)* | Webhook callback URL |
| `ADMIN_USERNAME` | `admin` | Admin panel username |
| `ADMIN_PASSWORD` | *(empty)* | Admin panel password |

## DNS Setup for HTTPS

After deployment, the script will output the server IP. To enable HTTPS:

1. Go to your DNS provider
2. Create an A record:
   - **Name**: your subdomain (e.g., `events`)
   - **Value**: the server IP from deploy output
   - **TTL**: 300 (or lowest available)
3. Wait for DNS propagation (usually 1-5 minutes)
4. Caddy will automatically obtain a Let's Encrypt certificate

## Troubleshooting

### Check cloud-init status
```bash
ssh root@SERVER_IP
cloud-init status
cat /var/log/cloud-init-output.log
```

### Check Docker containers
```bash
ssh root@SERVER_IP
cd /opt/datatalk-events
docker compose ps
docker compose logs app
docker compose logs caddy  # if using HTTPS
```

### Caddy certificate issues
```bash
# Check Caddy logs
docker compose logs caddy

# Verify DNS resolution
dig +short your-domain.com

# Ensure ports 80 and 443 are open
curl -v http://your-domain.com
```

### Application not responding
```bash
# Check if app is running
docker compose ps

# Check app logs
docker compose logs app --tail 50

# Check health endpoint
curl http://SERVER_IP:8000/health

# Restart
docker compose restart app
```

### Database issues
```bash
# Check data directory
ls -la /opt/datatalk-events/data/

# App data is stored in a Docker volume mount
docker compose exec app ls -la /app/data/
```

## Update Procedure

To deploy a new version:

```bash
ssh root@SERVER_IP
cd /opt/datatalk-events
git pull origin main
docker compose build app
docker compose up -d
```

Or with zero downtime (if using Caddy):

```bash
ssh root@SERVER_IP
cd /opt/datatalk-events
git pull origin main
docker compose build app
docker compose up -d --no-deps app
```

## Teardown / Cleanup

To completely remove the deployment:

```bash
# Delete the server
hcloud server delete datatalk-events

# Delete the firewall
hcloud firewall delete datatalk-events

# Delete the SSH key (optional)
hcloud ssh-key delete datatalk-events
```

Or delete everything at once:

```bash
export SERVER_NAME="datatalk-events"
hcloud server delete "$SERVER_NAME"
hcloud firewall delete "$SERVER_NAME"
hcloud ssh-key delete "$SERVER_NAME"
```
