#!/bin/sh
# Daily backup (cron: 0 2 * * * /app/scripts/backup.sh). Keeps >= 30 days.
set -e
DIR=${BACKUP_DIR:-./backups}; mkdir -p "$DIR"
PGPASSWORD=${DB_PASSWORD:-123} pg_dump -h ${DB_HOST:-localhost} -U ${DB_USER:-postgres} ${DB_NAME:-postgres} | gzip > "$DIR/ims_$(date +%F).sql.gz"
find "$DIR" -name 'ims_*.sql.gz' -mtime +30 -delete
