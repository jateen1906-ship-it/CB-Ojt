#!/bin/bash
set -e

PORT="${PORT:-8000}"
echo "=========================================="
echo "Starting CodeBridge Secondary Container"
echo "Nginx Reverse Proxy will bind to PORT: $PORT"
echo "=========================================="

sed -i "s/__PORT__/$PORT/g" /etc/nginx/nginx.conf

export APP_ENV=development

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
