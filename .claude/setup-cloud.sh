#!/bin/bash
# Setup for a Claude Code cloud environment for jeve.
#
# Paste this whole file into the environment's "Setup script" field. A
# one-liner that sources this path does not work: the setup script can run
# before the repo is cloned. This copy is the reviewable source of truth.
#
# Environment variables field:
#
#   CI=true
#   PYTHONUNBUFFERED=1
#   NEXT_TELEMETRY_DISABLED=1
#   NX_DAEMON=false
#   NX_NO_CLOUD=true
#   COREPACK_ENABLE_DOWNLOAD_PROMPT=0
#   JEVE_DATABASE_URL=postgresql://jeve:jeve@127.0.0.1:55432/jeve
#   DOPPLER_TOKEN_AGENT=<read-only service token for agent/prd>   (optional)
#   FLY_API_TOKEN=<fly tokens create readonly --org jeve-411>     (optional)
#   GH_TOKEN=<token>                                              (optional)
#
# JEVE_DATABASE_URL must stay the local database. The suite truncates, reseeds
# and drops tables in whatever it names, and db.dsn() would otherwise fall back
# to DATABASE_URL. Production is read through Doppler's agent/prd (OPS-0004).
#
# Network access: Custom, "Also include default list" checked, plus the hosts
# in docs/environment-variables.md ("Cloud agents"). The session's outbound
# traffic goes through an HTTP/HTTPS proxy, so production's Postgres is not
# reachable from here whatever the list says. Use the PlanetScale connector,
# or https://jeve-api.punitarani.com, instead.
#
# Every tool is installed at the version mise.toml pins, and each install is
# checked by asking the tool its version. The image's own uv and Node are not
# trusted: an image uv (0.8.17) that offered only Python 3.14.0rc2 once left
# the whole suite failing at collection. The script is idempotent and always
# exits 0. The full log is /tmp/setup-cloud.log.
set -uo pipefail
exec > >(tee /tmp/setup-cloud.log) 2>&1
export COREPACK_ENABLE_DOWNLOAD_PROMPT=0

T0=$SECONDS
FAILED=0
say() { printf 'setup: %s\n' "$*"; }
# `step` runs its command as an `if` condition, where bash ignores `set -e`,
# subshells included. So everything it runs chains with && or exits explicitly.
step() {
  local label="$1" t=$SECONDS; shift
  if "$@" >/tmp/setup-step.log 2>&1; then
    printf 'setup: %-30s ok   %4ds\n' "$label" "$((SECONDS - t))"
  else
    printf 'setup: %-30s FAIL %4ds\n' "$label" "$((SECONDS - t))"
    tail -15 /tmp/setup-step.log | sed 's/^/setup:   | /'
    FAILED=1
  fi
  hash -r
}
finish() {
  [ "$FAILED" = 1 ] && say "finished with failures in $((SECONDS - T0))s; full log /tmp/setup-cloud.log" \
                    || say "ready in $((SECONDS - T0))s"
  exit 0
}
as_root() { if [ "$(id -u)" = 0 ]; then "$@"; else sudo -n "$@"; fi; }
apt_install() {
  as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@" 2>/dev/null \
    || { as_root apt-get update -qq && as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "$@"; }
}
as_postgres() { if [ "$(id -u)" = 0 ]; then runuser -u postgres -- "$@"; else sudo -n -u postgres "$@"; fi; }

# --- the checkout ------------------------------------------------------------
is_repo() { [ -f "$1/mise.toml" ] && [ -d "$1/py/src/jeve" ]; }
if ! is_repo .; then
  for d in "$PWD"/* "$HOME"/* /workspace /workspace/* /repo /repos/* /workspaces/*; do
    is_repo "$d" && { cd "$d" && break; }
  done
fi
is_repo . || { say "no jeve checkout found from $PWD; run .claude/setup-cloud.sh by hand"; FAILED=1; finish; }
say "repo at $PWD"

pin() { sed -n "s/^$1 = \"\(.*\)\"/\1/p" mise.toml; }
NODE_V=$(pin node); PY_V=$(pin python); UV_V=$(pin uv); PNPM_V=$(pin pnpm)
ARCH=$(uname -m)   # x86_64 | aarch64

# --- guards --------------------------------------------------------------------
LOCAL_DB=1
for var in JEVE_DATABASE_URL DATABASE_URL; do
  case "${!var:-}" in
    ""|*@127.0.0.1[:/]*|*@localhost[:/]*) ;;
    *) say "WARNING $var is not this box's database; the suite would truncate it."
       say "        Fix the environment field. No database is touched until then."
       LOCAL_DB=0; FAILED=1 ;;
  esac
done
[ -n "${DOPPLER_TOKEN:-}" ] && { say "WARNING bare DOPPLER_TOKEN set; it hijacks every doppler call. Use DOPPLER_TOKEN_AGENT."; FAILED=1; }

# Tools land in ~/.local/bin and are linked into /usr/local/bin, which is on the
# session's PATH whatever shell it starts. ~/.bashrc alone was not enough:
# flyctl in ~/.fly/bin was installed and then not found.
BIN="$HOME/.local/bin"
mkdir -p "$BIN"
export PATH="$BIN:$PATH"
publish() {
  local b
  for b in "$@"; do
    [ -e "$BIN/$b" ] && as_root ln -sf "$BIN/$b" "/usr/local/bin/$b" 2>/dev/null
  done
  hash -r
}
grep -q '# jeve setup-cloud' "$HOME/.bashrc" 2>/dev/null \
  || printf '\n# jeve setup-cloud\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$HOME/.bashrc"

# --- Postgres on :55432 --------------------------------------------------------
# The repo's Compose file (postgres:18, as CI) when Docker works; otherwise a
# cluster of the box's own Postgres made to look the same: role and database
# `jeve`, superuser (the suite creates a database per xdist worker), UTF-8, UTC.
pg_up() { (exec 3<>/dev/tcp/127.0.0.1/55432) 2>/dev/null; }
distro_pg() (
  [ -d /usr/lib/postgresql ] || apt_install postgresql || exit 1
  v=$(ls /usr/lib/postgresql | sort -V | tail -1) && [ -n "$v" ] || exit 1
  # UTF-8 explicitly: as root with no locale set, a cluster comes up SQL_ASCII,
  # and the first migration's em dash fails to encode.
  pg_lsclusters -h | grep -q ' 55432 ' \
    || as_root pg_createcluster "$v" jeve -p 55432 --encoding UTF8 --locale C.UTF-8 || exit 1
  as_root pg_ctlcluster "$v" jeve start 2>/dev/null
  for _ in $(seq 1 20); do pg_up && break; sleep 1; done
  as_postgres psql -p 55432 -Xq -v ON_ERROR_STOP=1 <<'SQL' || exit 1
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'jeve') THEN
    CREATE ROLE jeve SUPERUSER LOGIN PASSWORD 'jeve';
  END IF;
END $$;
ALTER SYSTEM SET timezone = 'UTC';
SELECT pg_reload_conf();
SQL
  as_postgres psql -p 55432 -Xtqc "SELECT 1 FROM pg_database WHERE datname = 'jeve'" | grep -q 1 \
    || as_postgres createdb -p 55432 -O jeve jeve
)
if pg_up; then
  say "postgres :55432               skip (up)"
else
  if ! docker info >/dev/null 2>&1 && command -v dockerd >/dev/null; then
    # Started directly: the init script can die raising a file limit the box forbids.
    (as_root nohup dockerd >/tmp/dockerd.log 2>&1 &)
    for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
  fi
  if docker info >/dev/null 2>&1; then
    step "postgres 18 (compose)" docker compose up -d --wait
  fi
  pg_up || step "postgres (distro) :55432" distro_pg
fi

# --- toolchains, exactly as mise.toml pins them ---------------------------------
# `make` is how every documented command runs (make check, make e2e, …).
command -v make >/dev/null || step "make" apt_install make
if [ "$(uv --version 2>/dev/null | cut -d' ' -f2)" != "$UV_V" ]; then
  step "uv $UV_V" bash -o pipefail -c "
    curl -fsSL https://github.com/astral-sh/uv/releases/download/$UV_V/uv-$ARCH-unknown-linux-gnu.tar.gz \
      | tar -xz -C '$BIN' --strip-components 1 && '$BIN/uv' --version | grep -qF '$UV_V'"
fi
publish uv uvx

if [ "$(node -v 2>/dev/null)" != "v$NODE_V" ]; then
  node_install() (
    set -o pipefail
    a=$ARCH; [ "$a" = x86_64 ] && a=x64; [ "$a" = aarch64 ] && a=arm64
    d="$HOME/.local/node-v$NODE_V"
    if [ ! -x "$d/bin/node" ]; then
      rm -rf "$d" "$d.part" && mkdir -p "$d.part" \
        && curl -fsSL "https://nodejs.org/dist/v$NODE_V/node-v$NODE_V-linux-$a.tar.gz" \
           | tar -xz -C "$d.part" --strip-components 1 \
        && mv "$d.part" "$d" || exit 1
    fi
    ln -sf "$d/bin/node" "$d/bin/npm" "$d/bin/npx" "$d/bin/corepack" "$BIN/" \
      && [ "$("$BIN/node" -v)" = "v$NODE_V" ]
  )
  step "node $NODE_V" node_install
fi
publish node npm npx corepack

# pnpm through corepack, which honours package.json's packageManager pin.
if [ "$(pnpm --version 2>/dev/null)" != "$PNPM_V" ]; then
  step "pnpm $PNPM_V" bash -c \
    "corepack enable --install-directory '$BIN' pnpm && [ \"\$('$BIN/pnpm' --version)\" = '$PNPM_V' ]"
fi
publish pnpm

# uv installs the pinned Python itself; the venv is rebuilt if it was made
# with any other interpreter.
step "python $PY_V" uv python install "$PY_V"

# --- dependencies ----------------------------------------------------------------
if [ -f node_modules/.modules.yaml ] && [ ! pnpm-lock.yaml -nt node_modules/.modules.yaml ]; then
  say "pnpm install                  skip (current)"
else
  step "pnpm install" pnpm install --frozen-lockfile
fi
step "uv sync" bash -c "uv sync --frozen --directory py --python '$PY_V' \
  && uv run --directory py python -V | grep -qF '$PY_V'"

# One sim-day on rules into a never-seeded database, so `make api` has a town.
# The daemon migrates and seeds by itself; rules call no model.
if [ "$LOCAL_DB" = 1 ] && pg_up; then
  seeded=$(uv run --directory py python -c "
from jeve import db
with db.connect() as c:
    t = c.execute(\"SELECT to_regclass('sim_meta') IS NOT NULL AS t\").fetchone()['t']
    print('yes' if t and c.execute('SELECT 1 FROM sim_meta').fetchone() else 'no')" 2>/dev/null)
  if [ "$seeded" = yes ]; then
    say "local world                   skip (seeded)"
  else
    step "migrate + one sim-day" uv run --directory py python -m jeve.sim \
      --until-day 1 --day-minutes 0 --policy rules --calls replay --cassette off
  fi
fi

# Chromium for the Playwright specs; system libraries only the first time.
if ls -d "$HOME"/.cache/ms-playwright/chromium-* >/dev/null 2>&1; then
  step "playwright chromium" pnpm --filter @jeve/web exec playwright install chromium
else
  step "playwright chromium + deps" pnpm --filter @jeve/web exec playwright install --with-deps chromium
fi

# --- credentials ------------------------------------------------------------------
command -v psql >/dev/null || step "psql" apt_install postgresql-client
if [ -n "${DOPPLER_TOKEN_AGENT:-}" ] && ! command -v doppler >/dev/null; then
  step "doppler" bash -o pipefail -c "
    curl -fsSL 'https://cli.doppler.com/download?os=linux&arch=$([ "$ARCH" = x86_64 ] && echo amd64 || echo arm64)&format=tar' \
      | tar -xz -C '$BIN' doppler && '$BIN/doppler' --version"
  publish doppler
fi
if [ -n "${FLY_API_TOKEN:-}" ] && ! command -v flyctl >/dev/null; then
  step "flyctl" bash -o pipefail -c \
    "curl -fsSL https://fly.io/install.sh | FLYCTL_INSTALL='$HOME/.local' sh && '$BIN/flyctl' version"
  publish flyctl fly
fi
if [ -n "${GH_TOKEN:-}" ] && ! command -v gh >/dev/null; then
  step "gh" apt_install gh
fi

# What each credential reaches, never its value.
say "credentials:"
if [ -z "${DOPPLER_TOKEN_AGENT:-}" ]; then
  say "  doppler agent/prd            not configured (no DOPPLER_TOKEN_AGENT)"
elif ! DOPPLER_TOKEN="$DOPPLER_TOKEN_AGENT" doppler secrets -p agent -c prd --only-names >/dev/null 2>&1; then
  say "  doppler agent/prd            FAIL: token rejected or doppler missing"; FAILED=1
else
  say "  doppler agent/prd            ok"
  # Asks the database whether the URL can write (OPS-0004). Exit 2 here is the
  # proxy refusing Postgres, which is expected, not a setup failure.
  RO_URL="$(DOPPLER_TOKEN="$DOPPLER_TOKEN_AGENT" doppler secrets get JEVE_DATABASE_URL -p agent -c prd --plain 2>/dev/null)" \
    timeout 30 uv run --directory py python ../scripts/check_readonly_db.py >/tmp/setup-ro.log 2>&1
  case $? in
    0) say "  prod database                ok, $(tail -1 /tmp/setup-ro.log)" ;;
    1) say "  prod database                FAIL: $(tail -1 /tmp/setup-ro.log). Revoke DOPPLER_TOKEN_AGENT."; FAILED=1 ;;
    *) say "  prod database                unreachable from here (HTTP-only proxy); use the PlanetScale connector" ;;
  esac
fi
if [ -z "${FLY_API_TOKEN:-}" ]; then
  say "  flyctl                       not configured (no FLY_API_TOKEN)"
elif flyctl status -a jeve-backend >/dev/null 2>&1; then
  say "  flyctl                       ok (jeve-backend visible)"
else
  say "  flyctl                       FAIL: token rejected or flyctl missing"; FAILED=1
fi
if [ -z "${GH_TOKEN:-}" ]; then
  say "  gh                           not configured (no GH_TOKEN)"
elif gh api user >/dev/null 2>&1; then
  say "  gh                           ok"
else
  say "  gh                           FAIL: token rejected or gh missing"; FAILED=1
fi

say "node $(node -v 2>/dev/null) · pnpm $(pnpm -v 2>/dev/null) · $(uv --version 2>/dev/null) · $(uv run --directory py python -V 2>/dev/null)"
finish
