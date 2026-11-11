#!/bin/bash
# Restore a database dump made with scripts/export_db.ps1, replacing what's there.
#   bash deploy/restore_db.sh backups/build_advisor-2026-11-11.dump
set -euo pipefail
cd "$(dirname "$0")/.."

dump=${1:?usage: restore_db.sh backups/<file>.dump}
[ -f "$dump" ] || { echo "No such file: $dump" >&2; exit 1; }
compose=(docker compose -f docker-compose.prod.yml --env-file .env.prod)

echo "== Starting the database, stopping the app during the restore"
"${compose[@]}" up -d db
"${compose[@]}" stop web 2>/dev/null || true
until "${compose[@]}" exec -T db pg_isready -U build_advisor >/dev/null; do sleep 1; done

echo "== Restoring $dump (rebuilding the vector index takes a few minutes)"
# The dump is mounted at /backups. The HNSW index is built serially: a parallel
# build needs more shared memory (/dev/shm) than Docker gives a container and
# fails with "No space left on device". --exit-on-error makes any failure stop
# the restore instead of being skipped.
"${compose[@]}" exec -T \
  -e PGOPTIONS="-c maintenance_work_mem=256MB -c max_parallel_maintenance_workers=0" db \
  pg_restore -U build_advisor -d build_advisor --clean --if-exists --no-owner --exit-on-error \
  "/backups/$(basename "$dump")"

"${compose[@]}" exec -T db psql -U build_advisor -d build_advisor -At -c \
  "select count(*) || ' wiki pages' from wiki_document union all
   select count(*) || ' chunks, ' || count(embedding) || ' embedded' from wiki_chunk;"
indexes=$("${compose[@]}" exec -T db psql -U build_advisor -d build_advisor -At -c \
  "select count(*) from pg_indexes where indexname in ('chunk_embedding_hnsw', 'chunk_search_vector_gin')")
if [ "$indexes" != "2" ]; then
  echo "The search indexes are missing after the restore; not starting the app." >&2
  exit 1
fi

echo "== Starting the app"
"${compose[@]}" up -d web
echo "Done."
