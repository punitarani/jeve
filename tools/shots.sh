#!/usr/bin/env bash
# The thirteen shots, on a world of their own: its own database, its own API,
# its own production build of the site. Nothing a developer has running is
# touched, and two of these can run side by side on different ports.
#
#   SHOTS_OUT=docs/audit/2026-09-22 tools/shots.sh
#
#   SHOTS_DB      database to seed and drive      (default jeve_shots)
#   API_PORT      the API it starts               (default 8020)
#   WEB_PORT      the site it builds and starts   (default 3020)
#   SHOTS_OUT     where the PNGs and shots.jsonl go
#   SHOTS_POLICY  jev (strict replay, free) | rules — `rules` when the cassette
#                 is between recordings and a replay would miss
#   SHOTS_FAST=1  skip the 60-second and the state shots: a look, not a record
#   SHOTS_DIALOGUE=1  also render one dialogue. The only shot that reads `.env`
#                 and spends money (a fraction of a cent, through the gateway)
#
# Otherwise no key is needed and nothing is spent. Postgres must be up (`make db-up`).
set -uo pipefail
cd "$(dirname "$0")/.."

DB="${SHOTS_DB:-jeve_shots}"
API_PORT="${API_PORT:-8020}"
WEB_PORT="${WEB_PORT:-3020}"
POLICY="${SHOTS_POLICY:-jev}"
export SHOTS_OUT="${SHOTS_OUT:-docs/audit/shots}"
export WEB="http://localhost:${WEB_PORT}"
export API="http://127.0.0.1:${API_PORT}"
export JEVE_DATABASE_URL="postgresql://jeve:jeve@127.0.0.1:${JEVE_PG_PORT:-55432}/${DB}"
LOGS="$PWD/ops/shots-${WEB_PORT}"; mkdir -p "$LOGS"   # ops/* is ignored
DIST=".next-shots-${WEB_PORT}"

listening() { lsof -nP -t -iTCP:"$1" -sTCP:LISTEN 2>/dev/null; }
for port in "$API_PORT" "$WEB_PORT"; do
  if [ -n "$(listening "$port")" ]; then echo "port $port is busy; pick another" >&2; exit 2; fi
done

# `uv run` and `pnpm` are wrappers: killing them orphans the server. By port.
cleanup() {
  [ -n "${PACED:-}" ] && stop_paced
  for port in "$API_PORT" "$WEB_PORT"; do listening "$port" | xargs kill -9 2>/dev/null; done
}
trap cleanup EXIT

at() { echo $(( $1 * 86400 + $2 * 3600 + $3 * 60 )); }
sim() { (cd py && uv run python -m jeve.sim "$@" --policy "$POLICY" --calls replay) >> "$LOGS/sim.log" 2>&1; }
paced() { (cd py && exec uv run python -m jeve.sim --until "$1" --day-minutes "$2" --policy "$POLICY" --calls replay) >> "$LOGS/daemon.log" 2>&1 & PACED=$!; }
stop_paced() { pkill -TERM -P "$PACED" 2>/dev/null; kill -TERM "$PACED" 2>/dev/null; PACED=""; sleep 3; }
shoot() { node tools/screenshots.ts "$@"; }

docker exec jeve-postgres-1 psql -U jeve -d postgres -Atc "CREATE DATABASE ${DB}" >/dev/null 2>&1 || true
rm -f "$SHOTS_OUT/shots.jsonl"

echo "1/4  api on ${API_PORT}, database ${DB}"
sim --seed-world --until "$(at 0 7 0)" --day-minutes 0
ENVFILE=(); [ -n "${SHOTS_DIALOGUE:-}" ] && ENVFILE=(--env-file ../.env)
# (the odd expansion is for bash 3.2, where an empty array is "unbound")
(cd py && exec uv run ${ENVFILE[@]+"${ENVFILE[@]}"} uvicorn jeve.api.app:app --host 127.0.0.1 --port "$API_PORT") >> "$LOGS/api.log" 2>&1 &
for _ in $(seq 1 40); do curl -sf "$API/health" >/dev/null && break || sleep 1; done
curl -sf "$API/health" >/dev/null || { cat "$LOGS/api.log"; exit 1; }

echo "2/4  site on ${WEB_PORT} (production build)"
export NEXT_PUBLIC_JEVE_API="$API" JEVE_NEXT_DIST="$DIST"
pnpm --filter @jeve/web exec next build > "$LOGS/web-build.log" 2>&1 || { tail -40 "$LOGS/web-build.log"; exit 1; }
pnpm --filter @jeve/web exec next start --port "$WEB_PORT" > "$LOGS/web.log" 2>&1 &
for _ in $(seq 1 40); do curl -sf "$WEB" >/dev/null && break || sleep 1; done

echo "3/4  the day, hour by hour"
[ -n "${SHOTS_FAST:-}" ] || shoot state fresh-seed-nobody-has-decided
sim --until "$(at 1 7 30)" --day-minutes 0;  shoot time 0730
sim --until "$(at 1 12 30)" --day-minutes 0
paced "$(at 1 16 45)" 9
shoot bubble
if [ -n "${SHOTS_FAST:-}" ]; then
  # SHOTS_FAST also shortens `main`'s 60-second wait to three.
  shoot main
else
  shoot landing-live
  shoot main
fi
stop_paced
shoot quiet
[ -z "${SHOTS_DIALOGUE:-}" ] || shoot dialogue-static
[ -n "${SHOTS_FAST:-}" ] || SOFTWARE_GL=1 shoot time swiftshader-comparison
sim --until "$(at 1 18 30)" --day-minutes 0; shoot time 1830
sim --until "$(at 2 2 0)" --day-minutes 0;   shoot time 0200-night

echo "4/4  the states a visitor can land in"
if [ -z "${SHOTS_FAST:-}" ]; then
  shoot state routes
  listening "$API_PORT" | xargs kill -9 2>/dev/null
  shoot state api-down
fi
echo "shots in ${SHOTS_OUT}; logs in ${LOGS}"
