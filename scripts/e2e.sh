#!/usr/bin/env bash
# Gate 6: everything, from a clean checkout, in one command.
#
# Brings up Postgres, migrates, seeds, runs the fixture on rules, starts the
# API and the web app, runs the Playwright flow against them, writes the
# measured economics report, and tears down.
#
# Rules-only by default, so it costs nothing and needs no API key — a clean
# clone must not require credentials to prove the stack works. LIVE=1 is what
# spends money, and that path is still blocked by BLOCKED.md B1.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_PORT="${JEVE_API_PORT:-8010}"
WEB_PORT="${JEVE_WEB_PORT:-3010}"
DAYS="${JEVE_DAYS:-5}"
API_PID=""; WEB_PID=""

cleanup() {
  [ -n "$WEB_PID" ] && kill "$WEB_PID" 2>/dev/null || true
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true
  docker compose -p jeve-e2e down -v >/dev/null 2>&1 || true
}
trap cleanup EXIT

say() { printf '\n\033[1m── %s\033[0m\n' "$1"; }

say "1/6  database"
# A separate Compose project so a running dev stack is never disturbed, and
# port 0 so Docker picks a free one — a fixed port collides with the dev stack
# the moment anyone has it running, which is most of the time.
export JEVE_PG_PORT=0
docker compose -p jeve-e2e up -d --wait
PG_PORT="$(docker compose -p jeve-e2e port postgres 5432 | sed 's/.*://')"
export JEVE_DATABASE_URL="postgresql://jeve:jeve@127.0.0.1:${PG_PORT}/jeve"
echo "postgres on ${PG_PORT}"

say "2/6  install"
uv sync --directory py --quiet
pnpm install --frozen-lockfile --silent

say "3/6  offline checks"
make lint types test decisions

say "4/6  the world, on rules"
uv run --directory py python scripts/run_fixture.py --days "$DAYS" | tee /tmp/jeve-e2e-fixture.log

say "5/6  api + web + browser flow"
uv run --directory py uvicorn jeve.api.app:app --host 127.0.0.1 --port "$API_PORT" \
  > /tmp/jeve-e2e-api.log 2>&1 &
API_PID=$!
for _ in $(seq 1 40); do
  curl -sf "http://127.0.0.1:${API_PORT}/health" >/dev/null && break || sleep 1
done
curl -sf "http://127.0.0.1:${API_PORT}/health" >/dev/null || { cat /tmp/jeve-e2e-api.log; exit 1; }

NEXT_PUBLIC_JEVE_API="http://127.0.0.1:${API_PORT}" \
  pnpm --filter @jeve/web dev --port "$WEB_PORT" > /tmp/jeve-e2e-web.log 2>&1 &
WEB_PID=$!
for _ in $(seq 1 60); do
  curl -sf "http://localhost:${WEB_PORT}/" >/dev/null && break || sleep 1
done
curl -sf "http://localhost:${WEB_PORT}/" >/dev/null || { tail -30 /tmp/jeve-e2e-web.log; exit 1; }

JEVE_WEB_URL="http://localhost:${WEB_PORT}" pnpm --filter @jeve/web exec playwright test

say "6/6  measured economics"
uv run --directory py python scripts/economics.py --api "http://127.0.0.1:${API_PORT}" \
  --days "$DAYS" | tee ops/economics.md

# Deliberately not "ALL GATES PASSED". Gates 1-6 ran end to end, but every
# decision was made by rules because Jev is unreachable (BLOCKED.md B1), so
# the unit-economics gate has not been exercised. Saying otherwise here would
# be the stub-and-call-it-passed failure the brief rules out.
if grep -q "decided by a model | 0" ops/economics.md 2>/dev/null; then
  printf '\n\033[1;33mSTACK GREEN, ECONOMICS NOT MET\033[0m\n'
  printf 'Gates 1-6 ran from clean. Every decision was made by rules, so the\n'
  printf 'measured cost is ~$0 and proves nothing about the typed-decision\n'
  printf 'path. See BLOCKED.md B1 and ops/economics.md.\n'
else
  printf '\n\033[1;32mALL GATES PASSED\033[0m  report: ops/economics.md\n'
fi
