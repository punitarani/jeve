#!/bin/bash
# Setup for a Claude Code *cloud* environment for jeve.
#
# Paste this whole file into the environment's "Setup script" field. Do NOT
# paste a one-liner that sources this path: the setup script may run before the
# repo is cloned, or from another directory, and then it cannot find itself.
# This copy is the reviewable source of truth; keep the two in step.
#
# The matching "Environment variables" field. The first block carries no
# secrets:
#
#   CI=true                               NEXT_TELEMETRY_DISABLED=1
#   PYTHONUNBUFFERED=1                    NX_DAEMON=false
#   COREPACK_ENABLE_DOWNLOAD_PROMPT=0     NX_NO_CLOUD=true
#   JEVE_DATABASE_URL=postgresql://jeve:jeve@127.0.0.1:55432/jeve
#
# `JEVE_DATABASE_URL` is set explicitly, to the local Compose database, and
# must never be anything else here. `db.dsn()` falls back to `DATABASE_URL`,
# and the suite TRUNCATEs, reseeds and drops schemas in whatever database that
# names (`test_db` drops `public` outright). Pinning it means an image that
# happens to export `DATABASE_URL` cannot aim the suite somewhere real.
#
# `CI=true` makes pnpm refuse a lockfile mismatch instead of prompting and
# turns off Nx's TUI; nothing in jeve's own code reads it. Do not set
# NODE_ENV=production: pnpm would skip devDependencies, and nx, typescript and
# playwright are all devDependencies.
#
# The second block is credentials. Every one is optional — see "credentials"
# below for what each reaches, and why none of them is a bare `DOPPLER_TOKEN`:
#
#   DOPPLER_TOKEN_AGENT    read-only service token for agent/prd (OPS-0004)
#   FLY_API_TOKEN          `fly tokens create readonly --org jeve-411`
#   GH_TOKEN               gh
#
# Deliberately not in this field: OPENROUTER_API_KEY. Everything an agent
# needs runs on replay or rules — `make check`, `make e2e`, `make soak` — and
# spends nothing. `agent/prd` carries a key of its own, separate from
# production's, for the rare session that must call a model; it is used only
# by an explicit `doppler run -p agent -c prd -- …`.
#
# Network access: Custom, with "Also include default list" checked, plus the
# few hosts the default list lacks: astral.sh (uv's installer), the Playwright
# browser CDNs, and Doppler and Fly for the credentials below. The default list
# already has Docker Hub and its blob CDN, nodejs.org, npm, PyPI, GitHub
# release assets (where uv gets Python) and the Ubuntu archive. Without Docker
# this script falls back to the distribution's Postgres, which is enough for
# the suite but not for `make e2e` (it runs its own Compose project).
#
# Production's database is another matter. Every outbound connection goes
# through an HTTP/HTTPS proxy, and the Postgres wire protocol is neither, so
# allowing *.pg.psdb.cloud is unlikely to be enough. The credentials check
# below says whether this environment can reach it. If it cannot, read
# production through the PlanetScale connector, whose traffic does not use the
# session's network, or through https://jeve-api.punitarani.com.
#
# Runs on every session start, so every step is idempotent and skips work it
# has already done. It **always exits 0**: a setup script that fails takes the
# whole environment down with it, and a session that opens degraded can at
# least be used to find out why. Every step reports ok/FAIL and its wall time.
#
# Postgres starts in the background and the installs run underneath it: most
# of `docker compose up` on a cold box is an image pull, network waiting on
# network.
set -uo pipefail

T0=$SECONDS
FAILED=0
say() { printf 'setup: %s\n' "$*"; }
step() {
  local label="$1"; shift
  local t=$SECONDS
  if "$@" >/tmp/setup-step.log 2>&1; then
    printf 'setup: %-32s ok   %4ds\n' "$label" "$((SECONDS - t))"
  else
    printf 'setup: %-32s FAIL %4ds\n' "$label" "$((SECONDS - t))"
    tail -15 /tmp/setup-step.log | sed 's/^/setup:   | /'
    FAILED=1
  fi
}
# `curl … | sh` exits 0 when curl fails: sh reads an empty script and succeeds.
# That once reported "install mise ok" on a box where mise.run was blocked, and
# the next step died on "command not found". So an install counts only if the
# binary is on PATH afterwards.
install_tool() {  # install_tool <label> <binary> <shell command>
  step "$1" bash -o pipefail -c "$3
    command -v $2 >/dev/null || { echo '$2 is not on PATH after the install'; exit 1; }"
  hash -r
}
finish() {
  if [ "$FAILED" = "1" ]; then
    say "finished with failures in $((SECONDS - T0))s — the session is usable but incomplete"
  else
    say "ready in $((SECONDS - T0))s"
  fi
  exit 0
}

# --- find the repo ------------------------------------------------------------
# The working directory is not guaranteed to be the checkout, so look rather
# than assume.
is_repo() { [ -f "$1/nx.json" ] && [ -d "$1/py/src/jeve" ]; }
if ! is_repo .; then
  for d in "$PWD"/* "$HOME"/* /workspace /workspace/* /repo /repos/* /workspaces/*; do
    if is_repo "$d"; then cd "$d" && break; fi
  done
fi
if ! is_repo .; then
  say "WARNING no jeve checkout found (cwd $PWD). Nothing installed; open the"
  say "        session and run .claude/setup-cloud.sh by hand once you can see the repo."
  FAILED=1
  finish
fi
say "repo at $PWD"

# --- refuse to aim the suite at a real database ----------------------------------
# The environment variables field is free text, and a production URL pasted
# into JEVE_DATABASE_URL or DATABASE_URL would be the database `make test`
# truncates. The agents' role cannot write (OPS-0004), but that is the second
# line of defence, not the first.
LOCAL_DB=1
for var in JEVE_DATABASE_URL DATABASE_URL; do
  val="${!var:-}"
  [ -n "$val" ] || continue
  case "$val" in
    *@127.0.0.1:*|*@localhost:*|*@127.0.0.1/*|*@localhost/*) ;;
    *) say "WARNING $var points somewhere other than this box. The suite truncates"
       say "        whatever it names. Set it to the local database in the environment"
       say "        field; read production through Doppler instead (see credentials)."
       say "        Nothing below will touch a database until it is fixed."
       LOCAL_DB=0; FAILED=1 ;;
  esac
done
if [ -n "${DOPPLER_TOKEN:-}" ]; then
  say "WARNING a bare DOPPLER_TOKEN is set. It overrides every doppler call in the"
  say "        session; rename it DOPPLER_TOKEN_AGENT."
  FAILED=1
fi

# Everything below installs into $HOME/.local/bin. The session's shell reads
# ~/.bashrc, not this script's environment, so PATH goes there too (once).
mkdir -p "$HOME/.local/bin"
export PATH="$HOME/.local/bin:$HOME/.fly/bin:$PATH"
if ! grep -q '# jeve setup-cloud' "$HOME/.bashrc" 2>/dev/null; then
  cat >> "$HOME/.bashrc" <<'EOF'
# jeve setup-cloud: tools installed by .claude/setup-cloud.sh
export PATH="$HOME/.local/bin:$HOME/.fly/bin:$PATH"
EOF
fi

# --- Postgres first; the installs run underneath its image pull ---------------
# A fresh cloud box often has docker installed but no daemon running, and its
# init script can fail before starting one (it raises a file limit the box's
# hard limit forbids). Launching dockerd directly skips that.
if ! docker info >/dev/null 2>&1 && command -v dockerd >/dev/null 2>&1; then
  step "start dockerd" bash -c '
    (sudo -n true 2>/dev/null && sudo -n nohup dockerd || nohup dockerd) >/tmp/dockerd.log 2>&1 &
    for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && exit 0; sleep 1; done
    exit 1'
fi

PG_PENDING=0
PG_T0=$SECONDS
rm -f /tmp/pg.rc
pg_ready() { pg_isready -h 127.0.0.1 -p 55432 >/dev/null 2>&1 \
             || (exec 3<>/dev/tcp/127.0.0.1/55432) 2>/dev/null; }
if pg_ready; then
  say "postgres :55432                  skip (already up)"
elif docker info >/dev/null 2>&1; then
  # The repo's own docker-compose.yml: postgres:18-alpine on 55432, UTC, the
  # same image CI's service container runs.
  ( docker compose up -d --wait > /tmp/pg.log 2>&1; echo $? > /tmp/pg.rc ) &
  PG_PENDING=1
  say "postgres 18 (compose) starting in the background"
else
  # No Docker: the distribution's Postgres, made to look like the Compose one —
  # port 55432, role and database `jeve`, UTC. CI runs 18; this may be older.
  say "Docker is unavailable; installing the distribution's Postgres instead"
  step "apt: postgresql" bash -c '
    sudo -n apt-get update -qq &&
    sudo -n DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends postgresql'
  # Explicit exits, not `set -e`: `step` runs its command as an `if`
  # condition, where bash ignores errexit, subshells included.
  distro_cluster() (
    v=$(ls /usr/lib/postgresql | sort -V | tail -1) && [ -n "$v" ] || exit 1
    pg_lsclusters -h 2>/dev/null | grep -q ' 55432 ' \
      || sudo -n pg_createcluster "$v" jeve -p 55432 >/dev/null || exit 1
    sudo -n pg_ctlcluster "$v" jeve start 2>/dev/null || true
    for _ in $(seq 1 20); do pg_isready -h 127.0.0.1 -p 55432 >/dev/null && break; sleep 1; done
    # SUPERUSER, as in Compose: the suite creates a database per xdist worker.
    sudo -n -u postgres psql -p 55432 -Xq -v ON_ERROR_STOP=1 <<'SQL'
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'jeve') THEN
    CREATE ROLE jeve SUPERUSER LOGIN PASSWORD 'jeve';
  END IF;
END $$;
ALTER SYSTEM SET timezone = 'UTC';
SELECT pg_reload_conf();
SQL
    [ $? = 0 ] || exit 1
    sudo -n -u postgres psql -p 55432 -Xtqc "SELECT 1 FROM pg_database WHERE datname = 'jeve'" \
      | grep -q 1 || sudo -n -u postgres createdb -p 55432 -O jeve jeve
  )
  step "postgres cluster :55432" distro_cluster
fi

# --- toolchains, while the image comes down --------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  install_tool "install uv" uv 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi

# Node is pinned in mise.toml. Next 16 and pnpm 12 both want a modern one, so
# anything older than the pin's major is replaced by the pin itself, straight
# from nodejs.org. Not by installing mise first: that is one more download,
# from GitHub, which a network policy may refuse, to reach the same tarball.
node_ok() {
  command -v node >/dev/null 2>&1 \
    && [ "$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null)" -ge 24 ] 2>/dev/null
}
# Explicit exits, not `set -e`, for the reason given at distro_cluster: an
# errexit version of this moved an empty directory into place when the
# download failed, and the next run unpacked Node inside it.
node_from_pin() (
  set -o pipefail
  v=$(sed -n 's/^node = "\(.*\)"/\1/p' mise.toml) && [ -n "$v" ] || exit 1
  a=$(uname -m); case "$a" in x86_64) a=x64 ;; aarch64|arm64) a=arm64 ;; esac
  d="$HOME/.local/node-v$v"
  if [ ! -x "$d/bin/node" ]; then
    rm -rf "$d" "$d.part" && mkdir -p "$d.part" \
      && curl -fsSL "https://nodejs.org/dist/v$v/node-v$v-linux-$a.tar.gz" \
         | tar -xz -C "$d.part" --strip-components 1 \
      && mv "$d.part" "$d" || exit 1
  fi
  ln -sf "$d/bin/node" "$d/bin/npm" "$d/bin/npx" "$d/bin/corepack" "$HOME/.local/bin/" \
    && "$HOME/.local/bin/node" -v
)
if ! node_ok; then
  step "node (mise.toml pin)" node_from_pin
  hash -r
fi

# pnpm is whatever package.json's packageManager pins (12.x), via corepack:
# the lockfile is in pnpm 12's two-document format, which older pnpm misreads.
if ! pnpm --version 2>/dev/null | grep -q '^12\.'; then
  step "pnpm (corepack)" bash -c \
    'corepack enable --install-directory "$HOME/.local/bin" pnpm && pnpm --version'
fi

if [ ! -f node_modules/.modules.yaml ] || [ pnpm-lock.yaml -nt node_modules/.modules.yaml ]; then
  step "pnpm install" pnpm install --frozen-lockfile
else
  say "pnpm install                     skip (node_modules current)"
fi
# There is no root pyproject.toml; the project is py/. uv fetches the Python
# it pins (>=3.14) if the image's is older.
step "uv sync" uv sync --frozen --directory py

# --- now wait for Postgres, then give it a world -----------------------------------
if [ "$PG_PENDING" = "1" ]; then
  for _ in $(seq 1 180); do [ -f /tmp/pg.rc ] && break; sleep 2; done
  if [ ! -f /tmp/pg.rc ]; then
    printf 'setup: %-32s FAIL %4ds (timed out at six minutes)\n' "postgres (compose)" "$((SECONDS - PG_T0))"
    tail -15 /tmp/pg.log 2>/dev/null | sed 's/^/setup:   | /'
    FAILED=1
  elif [ "$(cat /tmp/pg.rc)" != "0" ]; then
    printf 'setup: %-32s FAIL %4ds\n' "postgres (compose)" "$((SECONDS - PG_T0))"
    tail -15 /tmp/pg.log 2>/dev/null | sed 's/^/setup:   | /'
    say "  hint: a 403 on CONNECT to a docker.com CDN host is the network policy"
    say "  refusing the image's layers. Raise it, or remove Docker from the image"
    say "  path and let this script use the distribution's Postgres."
    FAILED=1
  else
    printf 'setup: %-32s ok   %4ds\n' "postgres (compose)" "$((SECONDS - PG_T0))"
  fi
fi

# One sim-day on rules, so `make api` and the web app have a town to show. Only
# on a database that has never been seeded: the daemon migrates and seeds on
# its own when `sim_meta` is empty, and a world that exists is left alone.
# Rules and replay: this calls no model and cannot spend.
if [ "$LOCAL_DB" = "1" ] && pg_ready; then
  SEEDED="$(uv run --directory py python -c "
from jeve import db
with db.connect() as c:
    t = c.execute(\"SELECT to_regclass('sim_meta') IS NOT NULL AS t\").fetchone()['t']
    print('yes' if t and c.execute('SELECT 1 FROM sim_meta').fetchone() else 'no')
" 2>/dev/null)"
  if [ "$SEEDED" = "yes" ]; then
    say "local world                      skip (already seeded)"
  else
    step "migrate + one sim-day (rules)" uv run --directory py python -m jeve.sim \
      --until-day 1 --day-minutes 0 --policy rules --calls replay --cassette off
  fi
fi

# --- credentials: the services a laptop has and a cloud box does not ---------------
# There is no browser here, so nothing can run an OAuth flow. Each CLI reads
# its token from the environment under its own name.
#
# Deliberately **not** a bare `DOPPLER_TOKEN`. A service token is bound to one
# config, so a bare one hijacks every `doppler` call in the session, including
# ones meant for another project. Name the project on each call:
#
#   DOPPLER_TOKEN="$DOPPLER_TOKEN_AGENT" \
#     doppler secrets get JEVE_DATABASE_URL -p agent -c prd --plain
#
# `agent/prd` is a project of its own, not a branch of `worker/prd` (OPS-0004):
# production's knobs copied, none of its credentials. Its database URLs name a
# role that can only SELECT. Never write that URL into `.env` or
# JEVE_DATABASE_URL — `make` reads `.env`, and the suite would then be pointed
# at production. Query it directly:
#
#   PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=60000' \
#     psql "$(DOPPLER_TOKEN=$DOPPLER_TOKEN_AGENT doppler secrets get \
#             JEVE_DATABASE_URL -p agent -c prd --plain)" -X
#
# or run the API over production's data, read-only, on :8000:
#
#   DOPPLER_TOKEN="$DOPPLER_TOKEN_AGENT" doppler run -p agent -c prd -- make api
if [ -n "${DOPPLER_TOKEN_AGENT:-}" ] && ! command -v doppler >/dev/null 2>&1; then
  # --install-path skips the package-manager route, which wants sudo and a key.
  install_tool "install doppler" doppler \
    'curl -fsSL https://cli.doppler.com/install.sh \
       | sh -s -- --no-package-manager --install-path "$HOME/.local/bin"'
fi
if [ -n "${FLY_API_TOKEN:-}" ] && ! command -v flyctl >/dev/null 2>&1; then
  install_tool "install flyctl" flyctl 'curl -fsSL https://fly.io/install.sh | sh'
fi
if [ -n "${GH_TOKEN:-}" ] && ! command -v gh >/dev/null 2>&1; then
  install_tool "install gh" gh '
    v=$(curl -fsSL https://api.github.com/repos/cli/cli/releases/latest \
        | grep -m1 "\"tag_name\"" | cut -d\" -f4 | tr -d v)
    a=$(uname -m); case "$a" in x86_64) a=amd64 ;; aarch64|arm64) a=arm64 ;; esac
    curl -fsSL "https://github.com/cli/cli/releases/download/v${v}/gh_${v}_linux_${a}.tar.gz" \
      | tar -xz -C /tmp
    install -m 0755 "/tmp/gh_${v}_linux_${a}/bin/gh" "$HOME/.local/bin/gh"'
fi
if ! command -v psql >/dev/null 2>&1; then
  step "apt: postgresql-client" bash -c \
    'sudo -n apt-get install -y --no-install-recommends postgresql-client \
     || (sudo -n apt-get update -qq && sudo -n apt-get install -y --no-install-recommends postgresql-client)'
fi

# Report what each credential actually reaches, not that a variable is set: an
# expired token looks identical to a working one until something needs it.
# Never prints a value.
say "credentials:"
if [ -n "${DOPPLER_TOKEN_AGENT:-}" ] && command -v doppler >/dev/null 2>&1; then
  if DOPPLER_TOKEN="$DOPPLER_TOKEN_AGENT" doppler secrets -p agent -c prd \
       --only-names >/dev/null 2>&1; then
    printf 'setup:   %-32s ok\n' "doppler agent/prd"
    # Prove the database credential is read-only, from the database's own
    # catalogue, rather than trusting the config's name (OPS-0004).
    RO_URL="$(DOPPLER_TOKEN="$DOPPLER_TOKEN_AGENT" doppler secrets get JEVE_DATABASE_URL \
                -p agent -c prd --plain 2>/dev/null)" \
      uv run --directory py python ../scripts/check_readonly_db.py > /tmp/setup-ro.log 2>&1
    case $? in
      0) printf 'setup:   %-32s ok (%s)\n' "prod database" "$(tail -1 /tmp/setup-ro.log)" ;;
      1) printf 'setup:   %-32s FAIL — %s. Revoke DOPPLER_TOKEN_AGENT now.\n' \
           "prod database" "$(tail -1 /tmp/setup-ro.log)"; FAILED=1 ;;
      *) printf 'setup:   %-32s FAIL — %s (URL unset, network policy, or role gone)\n' \
           "prod database" "$(tail -1 /tmp/setup-ro.log)"; FAILED=1 ;;
    esac
  else
    printf 'setup:   %-32s FAIL — token rejected, revoked or wrong config\n' "doppler agent/prd"
    FAILED=1
  fi
else
  say "  doppler                          absent (no DOPPLER_TOKEN_AGENT)"
fi
if [ -n "${FLY_API_TOKEN:-}" ] && command -v flyctl >/dev/null 2>&1; then
  if flyctl status -a jeve-backend >/dev/null 2>&1; then
    say "  flyctl                           ok (jeve-backend visible)"
  else
    say "  flyctl                           FAIL — token rejected, expired, or not org jeve-411"
  fi
else
  say "  flyctl                           absent (no FLY_API_TOKEN)"
fi
if [ -n "${GH_TOKEN:-}" ] && command -v gh >/dev/null 2>&1; then
  gh auth status >/dev/null 2>&1 \
    && say "  gh                               ok" \
    || say "  gh                               FAIL — token rejected"
else
  say "  gh                               absent (no GH_TOKEN)"
fi

# --- browser for the Playwright specs (`make e2e`) -----------------------------
if [ ! -d "$HOME/.cache/ms-playwright" ]; then
  step "playwright chromium" pnpm --filter @jeve/web exec playwright install --with-deps chromium
fi

uv run --directory py python -c "
import platform, sys
print(f'setup: python {platform.python_version()} on {sys.platform}-{platform.machine()}')
" 2>/dev/null || true
say "node $(node -v 2>/dev/null) · pnpm $(pnpm -v 2>/dev/null) · $(uv --version 2>/dev/null)"

finish
