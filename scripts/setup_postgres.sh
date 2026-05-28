#!/usr/bin/env bash
# Re:Chord Postgres bootstrap (POSIX / Linux / macOS / WSL).
#
# Creates the ``rechord`` role + database if they don't exist, then runs
# Alembic migrations. Idempotent — safe to re-run after schema bumps.
#
# Usage:
#   ./scripts/setup_postgres.sh                              # local default
#   PGHOST=db.abc.supabase.co \
#     PGADMINUSER=postgres PGADMINPASSWORD='...' \
#     DBNAME=postgres ./scripts/setup_postgres.sh            # Supabase

set -euo pipefail

PGHOST=${PGHOST:-localhost}
PGPORT=${PGPORT:-5432}
PGADMINUSER=${PGADMINUSER:-postgres}
DBNAME=${DBNAME:-rechord}
DBUSER=${DBUSER:-rechord}
DBPASSWORD=${DBPASSWORD:-rechord_dev}

if [[ -z "${PGADMINPASSWORD:-}" ]]; then
    read -rs -p "Postgres admin ($PGADMINUSER) password: " PGADMINPASSWORD
    echo
fi

export PGPASSWORD="$PGADMINPASSWORD"

psql_cmd() {
    psql -h "$PGHOST" -p "$PGPORT" -U "$PGADMINUSER" -v ON_ERROR_STOP=1 "$@"
}

echo "[setup_postgres] ensuring role '$DBUSER'..."
if [[ "$(psql_cmd -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DBUSER'")" != "1" ]]; then
    psql_cmd -d postgres -c "CREATE ROLE $DBUSER LOGIN PASSWORD '$DBPASSWORD';"
    echo "  ✓ role created"
else
    echo "  ✓ role already exists"
fi

echo "[setup_postgres] ensuring database '$DBNAME'..."
if [[ "$(psql_cmd -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$DBNAME'")" != "1" ]]; then
    psql_cmd -d postgres -c "CREATE DATABASE $DBNAME OWNER $DBUSER ENCODING 'UTF8';"
    echo "  ✓ database created"
else
    echo "  ✓ database already exists"
fi

psql_cmd -d "$DBNAME" -c "GRANT ALL PRIVILEGES ON DATABASE $DBNAME TO $DBUSER;"

unset PGPASSWORD
DB_URL="postgresql+asyncpg://${DBUSER}:${DBPASSWORD}@${PGHOST}:${PGPORT}/${DBNAME}"
echo "[setup_postgres] running alembic upgrade head..."
echo "  DATABASE_URL=$DB_URL"

DATABASE_URL="$DB_URL" uv run alembic -c backend/app/db/alembic.ini upgrade head

echo
echo "[setup_postgres] DONE"
echo "Add this to your .env:"
echo "  DATABASE_URL=$DB_URL"
