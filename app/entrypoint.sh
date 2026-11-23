#!/bin/sh
set -e

case "$1" in
  web)
    python manage.py migrate --noinput
    python manage.py ensure_admin
    exec gunicorn config.wsgi:application \
      --bind 0.0.0.0:8000 \
      --workers "${GUNICORN_WORKERS:-3}" \
      --timeout 120 \
      --access-logfile - \
      --forwarded-allow-ips="*"
    ;;
  worker)
    # web migratsiyalarni bajarguncha kutish
    python manage.py wait_for_migrations
    exec python manage.py run_worker
    ;;
  *)
    exec "$@"
    ;;
esac
