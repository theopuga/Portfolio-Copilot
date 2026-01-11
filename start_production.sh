#!/bin/bash
# Production startup script for Portfolio Copilot API
# Optimized for localhost deployment

set -e

echo "Starting Portfolio Copilot API..."
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  WARNING: .env file not found!"
    echo "   Please create .env file from env.example"
    echo "   cp env.example .env"
    echo "   Then edit .env with your configuration"
    exit 1
fi

# Load environment variables
export $(cat .env | grep -v '^#' | xargs)

# Validate required environment variables
if [ -z "$BACKBOARD_API_KEY" ]; then
    echo "⚠️  WARNING: BACKBOARD_API_KEY not set in .env"
    echo "   App will run in fallback mode (in-memory storage)"
fi

# Set defaults
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8000}
WORKERS=${WORKERS:-4}
LOG_LEVEL=${LOG_LEVEL:-info}

# Normalize log level to lowercase for uvicorn (it requires lowercase)
LOG_LEVEL=$(echo "$LOG_LEVEL" | tr '[:upper:]' '[:lower:]')

echo "Configuration:"
echo "  Host: $HOST"
echo "  Port: $PORT"
echo "  Workers: $WORKERS"
echo "  Log Level: $LOG_LEVEL"
echo "  CORS Origins: ${CORS_ORIGINS:-*}"
echo ""

# Note about CORS for localhost
if [ "$CORS_ORIGINS" = "*" ]; then
    echo "ℹ️  CORS_ORIGINS is set to '*' (allow all)"
    echo "   This is acceptable for localhost-only deployment"
    echo ""
fi

echo "Starting uvicorn server..."
echo ""

# Start uvicorn with production settings
uvicorn backend.main:app \
    --host "$HOST" \
    --port "$PORT" \
    --workers "$WORKERS" \
    --log-level "$LOG_LEVEL" \
    --no-access-log \
    --proxy-headers \
    --forwarded-allow-ips="*"

