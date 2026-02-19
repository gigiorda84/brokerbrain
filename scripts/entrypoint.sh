#!/bin/bash
set -e

echo "BrokerBot starting (ENVIRONMENT=${ENVIRONMENT:-development})"

if [ "${SKIP_MIGRATIONS:-false}" != "true" ]; then
    echo "Running database migrations..."
    alembic upgrade head
fi

exec "$@"
