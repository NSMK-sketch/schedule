#!/bin/sh
set -eu

mkdir -p /data

if [ ! -s /data/schedule.db ] && [ -s /opt/seed/schedule.db ]; then
    cp /opt/seed/schedule.db /data/schedule.db
    echo "schedule: copied the existing database into /data"
fi

chown -R app:app /data

exec runuser -u app -- gunicorn \
    --bind 0.0.0.0:8000 \
    --workers 1 \
    --threads 4 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile - \
    wsgi:app
