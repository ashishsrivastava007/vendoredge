#!/bin/bash
set -euo pipefail

: "${APP_DATABASE_PASSWORD:?APP_DATABASE_PASSWORD must be set for the local app role}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_password="$APP_DATABASE_PASSWORD" <<'SQL'
CREATE ROLE vendoredge_app LOGIN PASSWORD :'app_password';
SQL
