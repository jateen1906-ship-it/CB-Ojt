#!/bin/bash
# Render service #1: API gateway (public) + identity/project/workspace/payment/notification.
set -euo pipefail

export PORT="${PORT:-10000}"
# Respect APP_ENV from the Render dashboard; production by default so that
# insecure default secrets are rejected at boot instead of silently used.
export APP_ENV="${APP_ENV:-production}"

echo "=========================================="
echo "Starting CodeBridge Unified Container (APP_ENV=$APP_ENV)"
echo "Public API Gateway will bind to PORT: $PORT"
echo "=========================================="

exec python /app/render_launcher.py \
    identity-service:/app/services/identity-service:127.0.0.1:8001:codebridge_identity \
    project-service:/app/services/project-service:127.0.0.1:8002:codebridge_project \
    workspace-service:/app/services/workspace-service:127.0.0.1:8005:codebridge_workspace \
    payment-service:/app/services/payment-service:127.0.0.1:8008:codebridge_payment \
    notification-service:/app/services/notification-service:127.0.0.1:8009:codebridge_notification \
    api-gateway:/app/api-gateway:0.0.0.0:$PORT
