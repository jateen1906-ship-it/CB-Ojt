#!/bin/bash
set -e

PORT="${PORT:-8000}"
echo "=========================================="
echo "Starting CodeBridge Unified Container"
echo "Public API Gateway will bind to PORT: $PORT"
echo "=========================================="

sed -i "s/__PORT__/$PORT/g" /etc/supervisor/conf.d/supervisord.conf

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf
