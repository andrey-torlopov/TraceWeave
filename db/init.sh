#!/bin/sh
set -eu
TW_APP_PASSWORD=$(cat /run/secrets/db_app_password)
export TW_APP_PASSWORD
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<'SQL'
\getenv app_password TW_APP_PASSWORD
CREATE ROLE traceweave LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE DATABASE traceweave OWNER traceweave TEMPLATE template0 ENCODING 'UTF8';
REVOKE CONNECT ON DATABASE traceweave FROM PUBLIC;
GRANT CONNECT ON DATABASE traceweave TO traceweave;
SQL
unset TW_APP_PASSWORD
