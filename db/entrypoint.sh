#!/bin/sh
set -eu
# The PostgreSQL image starts as root solely to prepare private TLS material,
# then its official entrypoint drops privileges to postgres.
mkdir -p /run/traceweave-tls
cp /run/secrets/db_key /run/traceweave-tls/server.key
cp /run/secrets/db_cert /run/traceweave-tls/server.crt
chown postgres:postgres /run/traceweave-tls/server.key /run/traceweave-tls/server.crt
chmod 600 /run/traceweave-tls/server.key
chmod 644 /run/traceweave-tls/server.crt
exec /usr/local/bin/docker-entrypoint.sh "$@"
