#!/usr/bin/env bash
# Stage on Fly the worker secrets CI carries, read from Doppler (OPS-0004).
#
# The Braintrust keys sat in Doppler worker/prd for a day and never reached a
# machine: CI's DOPPLER_TOKEN is a service token for infra/ci, a service token
# can read only the one config it was made for, and `flyctl deploy` sets no
# secrets. Tracing was off, silently, by design (LLM-0008). So infra/ci holds
# a second read-only token, DOPPLER_WORKER_TOKEN, made for worker/prd alone.
# This asks it for exactly the names below — nothing else in worker/prd leaves
# Doppler — and stages them, so the `flyctl deploy` after it rolls them out in
# its one restart.
#
# Doppler is the truth for these names: a value there is set on Fly, and a
# name absent there is unset on Fly. Nothing else is carried.
#
# A missing or broken grant is reported, never fatal: the code has passed the
# suite and still ships. WORKER_SECRETS_STAGED=0 makes the tracing gate after
# the deploy fail the run instead, pointing back here.
#
# Needs doppler (DOPPLER_TOKEN for infra/ci), flyctl (FLY_API_TOKEN) and jq.
# Appends WORKER_SECRETS_STAGED, and each value it stages, to $GITHUB_ENV.
set -euo pipefail

NAMES=(BRAINTRUST_API_KEY BRAINTRUST_PROJECT_ID)
REQUIRED=BRAINTRUST_API_KEY
FLY_CONFIG="${FLY_CONFIG:-fly.toml}"
ENV_FILE="${GITHUB_ENV:-/dev/null}"
SETUP="create a read-only service token for Doppler worker/prd and store it in infra/ci as DOPPLER_WORKER_TOKEN (docs/deployment.md)"

not_staged() {
  echo "::error title=Worker secrets not staged::$1"
  echo "WORKER_SECRETS_STAGED=0" >> "$ENV_FILE"
  exit 0
}

# `--json` names only the secrets that exist, so absence is an empty result
# and not a failure; a token that cannot read the config still fails, and on
# infra/ci that is fatal, as it is for FLY_API_TOKEN.
grant="$(doppler secrets get DOPPLER_WORKER_TOKEN -p infra -c ci --json \
  --no-exit-on-missing-secret | jq -r '.DOPPLER_WORKER_TOKEN.computed // empty')"
[ -n "$grant" ] || not_staged "Doppler infra/ci has no DOPPLER_WORKER_TOKEN. To fix: $SETUP."
echo "::add-mask::$grant"

if ! found="$(DOPPLER_TOKEN="$grant" doppler secrets get "${NAMES[@]}" \
  -p worker -c prd --json --no-exit-on-missing-secret)"; then
  not_staged "DOPPLER_WORKER_TOKEN cannot read Doppler worker/prd. To fix: $SETUP."
fi

# Every decision is made before anything on Fly changes: a name Doppler lists
# without a readable value is not an absent name, and must not unset one.
on_fly="$(flyctl secrets list --config "$FLY_CONFIG" --json | jq -r '.[].name')"
import=""
unset_names=()
for name in "${NAMES[@]}"; do
  if ! jq -e --arg n "$name" 'has($n)' <<< "$found" > /dev/null; then
    if grep -qxF "$name" <<< "$on_fly"; then
      unset_names+=("$name")
    fi
    continue
  fi
  value="$(jq -r --arg n "$name" '.[$n].computed // empty' <<< "$found")"
  [ -n "$value" ] || not_staged "Doppler worker/prd lists $name but returned no value for it."
  echo "::add-mask::$value"
  # One line per secret, quoted: `fly secrets import` cuts an unquoted value
  # at `#`, and neither format has a way to carry a newline or a quote.
  case "$value" in
    *$'\n'* | *'"'*) not_staged "$name in Doppler worker/prd holds a newline or a double quote." ;;
  esac
  import+="$name=\"$value\""$'\n'
  echo "$name=$value" >> "$ENV_FILE"
done

if [ -n "$import" ]; then
  printf '%s' "$import" | flyctl secrets import --stage --config "$FLY_CONFIG"
fi
if [ "${#unset_names[@]}" -gt 0 ]; then
  flyctl secrets unset --stage --config "$FLY_CONFIG" "${unset_names[@]}"
fi

staged="$(grep -c . <<< "$import" || true)"
echo "staged $staged secret(s) from Doppler worker/prd; unset ${#unset_names[@]}"
if ! jq -e --arg n "$REQUIRED" 'has($n)' <<< "$found" > /dev/null; then
  # Carried faithfully all the same: Doppler says tracing is off, so it is.
  echo "::error title=No $REQUIRED::Doppler worker/prd has no $REQUIRED, so the app deploys with tracing off."
fi
echo "WORKER_SECRETS_STAGED=1" >> "$ENV_FILE"
