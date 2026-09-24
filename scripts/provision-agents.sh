#!/usr/bin/env bash
# Fill in and audit what a cloud agent may read of production (OPS-0004).
#
#   AGENTS_RO_URL='postgresql://<role>:<pw>@us-east-3.pg.psdb.cloud:5432/postgres?sslmode=verify-full' \
#     scripts/provision-agents.sh     # prove read-only, store in agent/prd, audit, mint a token
#   scripts/provision-agents.sh --audit
#
# Run it from a checkout, as a human who can write to Doppler's `agent`
# project and read `worker` and `infra`.
#
# The read-only role comes first, in the PlanetScale dashboard: the jeve
# database (us-east-3.pg.psdb.cloud) → branch `main` → Roles → New role,
# `agents_ro`, inheriting **only** `pg_read_all_data`. Its direct URL (port
# 5432) is AGENTS_RO_URL. The pooled URL is the same on 6432, which is how
# production's pair is shaped. The URL is proven read-only before it is stored.
#
# `agent/prd` is a project of its own, so nothing production gains later
# reaches it. What can go wrong is a hand copy, so the audit compares every
# value in it against every credential in `worker` and `infra`.
set -euo pipefail
command -v jq >/dev/null || { echo "needs jq"; exit 2; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
P=agent; C=prd
PRODUCTION=(worker/prd infra/prd infra/ci)

readonly_check() { RO_URL="$1" uv run -q --directory py python ../scripts/check_readonly_db.py; }

# A credential is anything whose name says so, or a URL carrying a password
# (OPENROUTER_BASE_URL is a URL and is not one).
is_credential() {
  [[ "$1" =~ (KEY|TOKEN|SECRET|PASSWORD) ]] || [[ "$2" =~ ://[^/@]+:[^/@]+@ ]]
}

audit() {
  local agents leaks=0 pc json name value
  agents="$(doppler secrets download -p "$P" -c "$C" --no-file --format json)"
  for pc in "${PRODUCTION[@]}"; do
    json="$(doppler secrets download -p "${pc%/*}" -c "${pc#*/}" --no-file --format json)"
    while IFS=$'\t' read -r name value; do
      [[ "$name" == DOPPLER_* || -z "$value" ]] && continue
      is_credential "$name" "$value" || continue
      if jq -e --arg v "$value" 'any(.[]; . == $v)' <<<"$agents" >/dev/null; then
        echo "LEAK  $P/$C holds the value of $pc $name"; leaks=1
      fi
    done < <(jq -r 'to_entries[] | [.key, .value] | @tsv' <<<"$json")
  done
  for name in JEVE_DATABASE_URL JEVE_DATABASE_POOLED_URL; do
    value="$(jq -r --arg k "$name" '.[$k] // empty' <<<"$agents")"
    if [ -z "$value" ]; then
      echo "unset $name"; leaks=1
    elif ! readonly_check "$value" >/dev/null; then
      echo "LEAK  $name is not a read-only role (or is unreachable)"; leaks=1
    fi
  done
  [ "$leaks" = 0 ] && echo "audit: $P/$C holds no production credential, and its database URLs cannot write"
  return "$leaks"
}

if [ "${1:-}" = "--audit" ]; then audit; exit; fi

: "${AGENTS_RO_URL:?set AGENTS_RO_URL to the read-only role direct URL, see the header}"
POOLED_URL="$(sed -E 's#(@[^/:]+):5432/#\1:6432/#' <<<"$AGENTS_RO_URL")"

echo "1/3  the role cannot write"
readonly_check "$AGENTS_RO_URL"
readonly_check "$POOLED_URL"

echo "2/3  stored in $P/$C, then audited"
doppler secrets set -p "$P" -c "$C" --silent \
  JEVE_DATABASE_URL="$AGENTS_RO_URL" JEVE_DATABASE_POOLED_URL="$POOLED_URL"
audit

echo "3/3  service token (read-only, shown once)"
echo "DOPPLER_TOKEN_AGENT=$(doppler configs tokens create "claude-cloud-$(date +%Y%m%d)" \
  -p "$P" -c "$C" --plain)"
cat <<'EOF'

Put it in the cloud environment's variables. Optionally, a read-only Fly token
for `fly logs` / `fly status` that expires on its own in 90 days:

  fly tokens create readonly --org jeve-411 --name claude-cloud-agents --expiry 2160h
EOF
