#!/usr/bin/env bash
# Re:Chord Postgres backup — gzip'd pg_dump rotated by date.
#
# Usage:
#   ./scripts/backup_postgres.sh                  # default ./backups/
#   DUMP_DIR=/mnt/backups ./scripts/backup_postgres.sh
#   PGHOST=db.foo.supabase.co PGUSER=postgres \
#     PGPASSWORD='...' DBNAME=postgres ./scripts/backup_postgres.sh
#
# Cron suggestion (daily 03:00 KST):
#   0 18 * * * cd /opt/rechord && DUMP_DIR=/mnt/backups ./scripts/backup_postgres.sh

set -euo pipefail

PGHOST=${PGHOST:-localhost}
PGPORT=${PGPORT:-5432}
PGUSER=${PGUSER:-rechord}
DBNAME=${DBNAME:-rechord}
DUMP_DIR=${DUMP_DIR:-./backups}
RETAIN_DAYS=${RETAIN_DAYS:-30}

mkdir -p "$DUMP_DIR"

stamp=$(date +"%Y-%m-%d_%H-%M")
out="$DUMP_DIR/${DBNAME}_${stamp}.sql.gz"

# --no-owner / --no-privileges so the dump restores cleanly into a
# different user (managed DB onboarding, account migration, …).
# Adding --serializable-deferrable for a consistent snapshot under
# concurrent writes; falls back gracefully on older Postgres versions.
echo "[backup] dumping $DBNAME@$PGHOST → $out"
pg_dump \
    --host="$PGHOST" --port="$PGPORT" --username="$PGUSER" \
    --dbname="$DBNAME" \
    --no-owner --no-privileges \
    --serializable-deferrable \
    | gzip -c > "$out"

size=$(stat -c %s "$out" 2>/dev/null || stat -f %z "$out")
echo "[backup] OK ($(numfmt --to=iec $size 2>/dev/null || echo $size bytes))"

# --- retention --------------------------------------------------------
echo "[backup] expiring dumps older than ${RETAIN_DAYS} days..."
find "$DUMP_DIR" -name "${DBNAME}_*.sql.gz" -mtime "+${RETAIN_DAYS}" -print -delete

# --- freshness sentinel (consumed by monitoring) ---------------------
echo "$out" > "$DUMP_DIR/.last_successful_dump"
date -Iseconds > "$DUMP_DIR/.last_successful_dump_ts"
