#!/bin/sh
set -eu
: "${STRENGTHOS_BACKUP_BUCKET:?Set a Mumbai Object Storage bucket}"
: "${STRENGTHOS_OBJECT_NAMESPACE:?Set the OCI namespace}"
umask 077
backup_file=$(mktemp /var/lib/strengthos/backup.XXXXXX)
trap 'rm -f "$backup_file"' EXIT
PGHOST=/var/run/postgresql PGUSER=strengthos PGDATABASE=strengthos \
  pg_dump --format=custom --no-owner --file="$backup_file"
pg_restore --list "$backup_file" >/dev/null
oci os object put --auth instance_principal --namespace-name "$STRENGTHOS_OBJECT_NAMESPACE" \
  --bucket-name "$STRENGTHOS_BACKUP_BUCKET" --name "strengthos/$(date -u +%Y-%m-%dT%H-%M-%SZ).dump" \
  --file "$backup_file" --force >/dev/null
