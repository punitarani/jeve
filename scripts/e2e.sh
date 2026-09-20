#!/usr/bin/env bash
# Everything, from a clean checkout, in one command.
#
# Brings up Postgres, migrates, seeds, runs the world with Jev deciding, starts
# the API and the web app, drives a real browser through them, writes the
# measured economics report, and tears down.
#
#   make e2e            strict replay from the committed cassette. Free, needs
#                       no API key, and never constructs a gateway. A call the
#                       cassette does not hold is a failure, not a fallback.
#   LIVE=1 make e2e     hit-or-call: replays what the cassette has, pays for
#                       what it lacks, appends it. The only mode that writes
#                       the tracked ops/economics.md.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

API_PORT="${JEVE_API_PORT:-8010}"
WEB_PORT="${JEVE_WEB_PORT:-3010}"
DAYS="${JEVE_DAYS:-5}"
LOGS="$(mktemp -d "${TMPDIR:-/tmp}/jeve-e2e.XXXXXX")"
API_PID=""; WEB_PID=""; SIM_PID=""

if [ "${LIVE:-0}" = "1" ]; then
  CALLS=record
  [ -f .env ] || { echo "LIVE=1 needs a .env with OPENROUTER_API_KEY"; exit 2; }
  UVRUN=(uv run --directory py --env-file "$ROOT/.env")
else
  CALLS=replay
  UVRUN=(uv run --directory py)
fi

cleanup() {
  [ -n "$SIM_PID" ] && kill "$SIM_PID" 2>/dev/null || true
  [ -n "$WEB_PID" ] && kill "$WEB_PID" 2>/dev/null || true
  [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true
  # `pnpm` and `uv run` are wrappers: killing them orphans the server they
  # started, which then squats on the port and answers the *next* run's health
  # checks. Both ports were verified free on the way in, so whatever is
  # listening on them now is ours.
  if [ "${PORTS_OURS:-0}" = "1" ]; then
    for port in "$API_PORT" "$WEB_PORT"; do
      lsof -nP -t -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
    done
  fi
  docker compose -p jeve-e2e down -v >/dev/null 2>&1 || true
  echo "logs: $LOGS"
}
trap cleanup EXIT

say() { printf '\n\033[1m── %s\033[0m\n' "$1"; }

# A port someone else holds means the health checks below would pass against
# *their* server, and the run would go green having tested nothing of ours.
for port in "$API_PORT" "$WEB_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "port $port is already in use; set JEVE_API_PORT / JEVE_WEB_PORT"; exit 2
  fi
done
PORTS_OURS=1

say "1/6  database"
# A separate Compose project so a running dev stack is never disturbed, and
# port 0 so Docker picks a free one.
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

say "4/6  the world, decided by Jev (${CALLS})"
# Flat out to Friday lunchtime, when people are out and about. The last
# afternoon is left for a *paced* daemon to run while the browser watches, so
# "the hero advances on its own" is tested against a process that is really
# ticking. Same loop, same horizon: `--until` is what lets a wall-clock process
# and its replay end in the same place.
PACED_FROM=$(( 4 * 86400 + 13 * 3600 ))
"${UVRUN[@]}" python -m jeve.sim --seed-world --until "$PACED_FROM" --day-minutes 0 \
  --policy jev --calls "$CALLS" --stats "$LOGS/run-1.json" --verbose | tee "$LOGS/fixture.log"

say "5/6  api + web + browser flow"
uv run --directory py uvicorn jeve.api.app:app --host 127.0.0.1 --port "$API_PORT" \
  > "$LOGS/api.log" 2>&1 &
API_PID=$!
for _ in $(seq 1 40); do
  curl -sf "http://127.0.0.1:${API_PORT}/health" >/dev/null && break || sleep 1
done
curl -sf "http://127.0.0.1:${API_PORT}/health" >/dev/null || { cat "$LOGS/api.log"; exit 1; }

# A production build, not `next dev`: Next 16 holds a lock in its dev directory,
# so a second dev server beside a developer's own refuses to start. It is also
# the only place the TypeScript is compiled against the real page tree.
export NEXT_PUBLIC_JEVE_API="http://127.0.0.1:${API_PORT}"
export JEVE_NEXT_DIST=".next-e2e"
pnpm --filter @jeve/web exec next build > "$LOGS/web-build.log" 2>&1 \
  || { tail -40 "$LOGS/web-build.log"; exit 1; }
pnpm --filter @jeve/web exec next start --port "$WEB_PORT" > "$LOGS/web.log" 2>&1 &
WEB_PID=$!
for _ in $(seq 1 60); do
  curl -sf "http://localhost:${WEB_PORT}/" >/dev/null && break || sleep 1
done
curl -sf "http://localhost:${WEB_PORT}/" >/dev/null || { tail -30 "$LOGS/web.log"; exit 1; }

# The last afternoon, at four real seconds a tick, while the browser looks on.
"${UVRUN[@]}" python -m jeve.sim --until-day "$DAYS" --day-minutes 6.4 \
  --policy jev --calls "$CALLS" --stats "$LOGS/run-2.json" --verbose \
  > "$LOGS/daemon.log" 2>&1 &
SIM_PID=$!

JEVE_WEB_URL="http://localhost:${WEB_PORT}" pnpm --filter @jeve/web exec playwright test

# The report is about the whole fixture, so let the daemon reach its horizon.
for _ in $(seq 1 180); do kill -0 "$SIM_PID" 2>/dev/null || break; sleep 1; done
if kill -0 "$SIM_PID" 2>/dev/null; then
  echo "the paced daemon did not reach its horizon"; tail -20 "$LOGS/daemon.log"; exit 1
fi
wait "$SIM_PID" || { echo "the paced daemon failed"; tail -20 "$LOGS/daemon.log"; exit 1; }
tail -4 "$LOGS/daemon.log"

say "6/6  measured economics"
# Only a live run writes the tracked report. A replay reproduces the same
# figures — they are priced from the recorded calls — so it writes beside it
# and says so if the two have drifted, which means the world changed and the
# committed measurement no longer describes it.
REPORT="ops/economics.replay.md"
[ "$CALLS" = "record" ] && REPORT="ops/economics.md"
set +e
uv run --directory py python scripts/economics.py \
  --api "http://127.0.0.1:${API_PORT}" \
  --stats "$LOGS/run-1.json" --stats "$LOGS/run-2.json" > "$REPORT"
VERDICT=$?
set -e
cat "$REPORT"

if [ "$CALLS" = "replay" ] && [ -f ops/economics.md ]; then
  if ! diff <(grep -v '^\*\*This invocation' ops/economics.md) \
            <(grep -v '^\*\*This invocation' "$REPORT") >/dev/null; then
    printf '\n\033[1;33mnote:\033[0m this replay no longer matches the committed '
    printf 'ops/economics.md. Re-measure with LIVE=1 make e2e.\n'
  fi
fi

if [ "$VERDICT" = "0" ]; then
  printf '\n\033[1;32mALL GATES PASSED\033[0m  economics MET (%s)  report: %s\n' "$CALLS" "$REPORT"
elif [ "$VERDICT" = "3" ]; then
  printf '\n\033[1;33mSTACK GREEN, ECONOMICS NOT MET\033[0m  see %s\n' "$REPORT"
else
  exit "$VERDICT"
fi
