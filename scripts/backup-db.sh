#!/bin/bash
# Nightly Postgres backup → Cloudflare R2.
# Dumps the DB from the running `db` container, gzips it, uploads to R2 under
# backups/, and prunes local copies older than 7 days. Reuses the R2_* creds
# already in api/.env (the same bucket the app uploads media to).
#
# Install (run once, as the deploy user, from the api/ directory):
#   chmod +x scripts/backup-db.sh
#   ( crontab -l 2>/dev/null; echo "30 2 * * * cd $PWD && ./scripts/backup-db.sh >> /var/log/ptd-backup.log 2>&1" ) | crontab -
set -euo pipefail

cd "$(dirname "$0")/.."          # → api/
set -a; source .env; set +a       # load POSTGRES_* and R2_* vars

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="/tmp/ptd-${STAMP}.sql.gz"

echo "[backup] dumping database…"
docker compose exec -T db pg_dump -U "${POSTGRES_USER:-ptd_user}" "${POSTGRES_DB:-ptd}" | gzip > "$OUT"

echo "[backup] uploading to R2…"
docker run --rm \
  -e AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
  -e AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
  -e AWS_DEFAULT_REGION=auto \
  -v "$OUT:$OUT:ro" \
  amazon/aws-cli s3 cp "$OUT" "s3://${R2_BUCKET_NAME}/backups/$(basename "$OUT")" \
  --endpoint-url "https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

echo "[backup] pruning local dumps older than 7 days…"
find /tmp -name 'ptd-*.sql.gz' -mtime +7 -delete

echo "[backup] done: $(basename "$OUT")"
