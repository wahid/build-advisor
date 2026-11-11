#!/bin/bash
# Update the app on the server: pull the latest main and rebuild/restart what changed.
# Run as the deploy user in /srv/build-advisor (GitHub Actions does this over SSH).
set -euo pipefail
cd "$(dirname "$0")/.."

git fetch --quiet origin main
git reset --hard origin/main

docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build --remove-orphans
docker image prune -f >/dev/null

echo "Waiting for the app to become healthy..."
for _ in $(seq 1 60); do
  status=$(docker inspect -f '{{.State.Health.Status}}' "$(docker compose -f docker-compose.prod.yml ps -q web)")
  [ "$status" = "healthy" ] && echo "Deployed $(git rev-parse --short HEAD)" && exit 0
  sleep 5
done
echo "The app didn't become healthy; recent logs:" >&2
docker compose -f docker-compose.prod.yml logs --tail 50 web >&2
exit 1
