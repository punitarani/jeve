#!/usr/bin/env bash
# After a backend deploy: is tracing on, and is anything arriving? (OPS-0004)
#
# The first question fails the run, the second only warns. Getting the key
# onto the running app is CI's job now, so a run that cannot show it there is
# red. A span arriving also depends on Braintrust, and on the daemon having a
# tick to run (one parked on waiting_on_budget opens no span), so its absence
# is reported but does not fail the run.
#
# `health.tracing` comes from the api process, but `api` and `sim` are one Fly
# app with one set of secrets, so it speaks for the daemon's key too.
#
# Needs curl and jq. Reads JEVE_API (the public API origin), DEPLOY_STARTED,
# WORKER_SECRETS_STAGED, BRAINTRUST_API_KEY and BRAINTRUST_PROJECT_ID.
set -euo pipefail

GATE_S="${GATE_S:-120}"
SPAN_S="${SPAN_S:-300}"
POLL_S="${POLL_S:-10}"
BRAINTRUST_API="${BRAINTRUST_API:-https://api.braintrust.dev}"
PROJECT_NAME=jeve # tracing.py's DEFAULT_PROJECT, used when no id is set

if [ "${WORKER_SECRETS_STAGED:-0}" != 1 ]; then
  echo "::error title=Tracing not under CI's control::The worker secrets were not staged from Doppler; the error on the staging step says why."
  exit 1
fi
if [ -z "${JEVE_API:-}" ]; then
  echo "::error::The repository variable NEXT_PUBLIC_JEVE_API is empty, so /state cannot be checked."
  exit 1
fi

state_url="${JEVE_API%/}/state"
deadline=$((SECONDS + GATE_S))
tracing=unknown
while :; do
  if body="$(curl -fsS --max-time 15 "$state_url")"; then
    tracing="$(jq -r '.health.tracing' <<< "$body" 2> /dev/null || echo unreadable)"
    [ "$tracing" = true ] && break
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    echo "::error title=Tracing is off::$state_url reports health.tracing=$tracing ${GATE_S}s after the deploy. The app has no BRAINTRUST_API_KEY."
    exit 1
  fi
  sleep "$POLL_S"
done
echo "health.tracing is true at $state_url"

# -- spans: warn, never fail -------------------------------------------------

warn() {
  echo "::warning title=No Braintrust spans yet::$1 Look at sim_meta.status (a parked daemon ticks nothing) and \`fly logs --process sim\` for 'Dropping batch' or 'log request failed'."
  exit 0
}

[ -n "${BRAINTRUST_API_KEY:-}" ] || warn "The staging step exported no BRAINTRUST_API_KEY to ask with."
auth=(-H "Authorization: Bearer $BRAINTRUST_API_KEY")
project="${BRAINTRUST_PROJECT_ID:-}"
if [ -z "$project" ]; then
  project="$(curl -fsS --max-time 15 "${auth[@]}" \
    "$BRAINTRUST_API/v1/project?project_name=$PROJECT_NAME" |
    jq -r '.objects[0].id // empty')" || true
  [ -n "$project" ] || warn "No Braintrust project named $PROJECT_NAME is visible to the key."
fi
# Interpolated into a query below, so it must be an id and nothing else.
[[ "$project" =~ ^[A-Za-z0-9-]+$ ]] || warn "BRAINTRUST_PROJECT_ID is not a project id."

query="SELECT id, created FROM project_logs('$project') WHERE created > '${DEPLOY_STARTED:?}' LIMIT 1"
payload="$(jq -nc --arg q "$query" '{query: $q, fmt: "json"}')"
deadline=$((SECONDS + SPAN_S))
while :; do
  if rows="$(curl -fsS --max-time 30 "${auth[@]}" -H "Content-Type: application/json" \
    -d "$payload" "$BRAINTRUST_API/btql")"; then
    first="$(jq -r '(.data // .rows // [])[0].created // empty' <<< "$rows" 2> /dev/null || true)"
    if [ -n "$first" ]; then
      echo "::notice title=Braintrust is receiving spans::First span after the deploy at $first, project $project."
      exit 0
    fi
  fi
  [ "$SECONDS" -lt "$deadline" ] || warn "Nothing in project $project since $DEPLOY_STARTED after ${SPAN_S}s."
  sleep "$POLL_S"
done
