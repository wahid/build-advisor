#!/bin/bash
# Update the app on the server: pull the latest main and rebuild/restart what changed.
# Run as the deploy user in /srv/build-advisor (GitHub Actions does this over SSH).
set -euo pipefail
cd "$(dirname "$0")/.."

# Files created as root (e.g. .env.prod, a copied dump, a git command run as root)
# can't be updated by the deploy user.
if [ -n "$(find . -path ./backups -prune -o ! -user "$(id -un)" -print -quit)" ]; then
  echo "Some files in $(pwd) aren't owned by $(id -un). Fix as root with:" >&2
  echo "  chown -R $(id -un):$(id -gn) $(pwd)" >&2
  exit 1
fi

[ -f .env.prod ] || { echo "Create .env.prod first (see .env.prod.example)." >&2; exit 1; }
# Every compose call needs the same file and variables.
compose=(docker compose -f docker-compose.prod.yml --env-file .env.prod)

# Mounted into the web container; created here so Docker doesn't create it as root.
mkdir -p proxies

git fetch --quiet origin main
git reset --hard origin/main

"${compose[@]}" up -d --build --remove-orphans
docker image prune -f >/dev/null

echo "Waiting for the app to become healthy (the first start downloads the model)..."
for _ in $(seq 1 72); do
  container=$("${compose[@]}" ps -q web)
  status=$(docker inspect -f '{{.State.Health.Status}}' "$container" 2>/dev/null || echo missing)
  [ "$status" = "healthy" ] && echo "Deployed $(git rev-parse --short HEAD)" && exit 0
  sleep 5
done
echo "The app didn't become healthy within 6 minutes; recent logs:" >&2
"${compose[@]}" logs --tail 50 web >&2
exit 1
