#!/bin/bash
# Render service #2: nginx (public) + github/review/verification/admin/audit.
set -euo pipefail

export PORT="${PORT:-10000}"
export APP_ENV="${APP_ENV:-production}"

echo "=========================================="
echo "Starting CodeBridge Secondary Container (APP_ENV=$APP_ENV)"
echo "Nginx Reverse Proxy will bind to PORT: $PORT"
echo "=========================================="

sed -i "s/__PORT__/$PORT/g" /etc/nginx/nginx.conf
nginx -t
nginx   # daemonizes; the launcher below owns PID 1 and the Python services

exec python /app/render_launcher.py \
    github-service:/app/services/github-service:127.0.0.1:8003:codebridge_github \
    review-service:/app/services/review-service:127.0.0.1:8006:codebridge_review \
    verification-service:/app/services/verification-service:127.0.0.1:8007:codebridge_verification \
    admin-service:/app/services/admin-service:127.0.0.1:8010:codebridge_admin \
    audit-service:/app/services/audit-service:127.0.0.1:8011:codebridge_audit
