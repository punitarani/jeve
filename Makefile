# jeve — one command per thing.
.DEFAULT_GOAL := help
SHELL := /bin/bash
ROOT := $(shell pwd)

# A clean clone has no .env, and `uv run --env-file` hard-errors on a missing
# file. Replay and every offline check must work without credentials.
ENVFILE := $(if $(wildcard $(ROOT)/.env),--env-file $(ROOT)/.env,)
UV := uv run --directory $(ROOT)/py $(ENVFILE)

# Prefer Nx targets where they exist; fall back to direct commands for
# operations that aren't yet in the Nx graph or need special handling.
.PHONY: help
help: ## Show this
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[1m%-12s\033[0m %s\n", $$1, $$2}'

.PHONY: check
check: lint types test decisions ## Everything that must pass, offline

.PHONY: lint
lint: ## ruff check + format check
	@echo "Linting Python..."
	npx nx run py:lint
	# api/sim lint are per-app ruff views of the same package. Web has no
	# eslint config — its static gate is tsc strict under `make types`.
	@echo "Linting app views..."
	npx nx run-many -t lint --projects=api,sim

.PHONY: types
types: ## mypy --strict, and tsc over the web app
	@echo "Type checking Python..."
	npx nx run py:typecheck
	@echo "Type checking TypeScript..."
	npx nx run-many -t typecheck --projects=api,sim,web

.PHONY: test
test: ## pytest, no network
	@echo "Testing Python..."
	npx nx run py:test
	@echo "Testing applications..."
	# --parallel=1: api and sim tests share the dev database, and sim's daemon
	# subprocesses hold the writer lock — run in parallel and api's seeding
	# fixture loses the lock race to a daemon that is still finishing a tick.
	npx nx run-many -t test --projects=api,sim,web --parallel=1

.PHONY: decisions
decisions: ## Validate records; fail if generated artifacts are stale
	python3 scripts/gen-decisions.py --check
	python3 scripts/test_gen_decisions.py
	python3 scripts/test_run_confirmations.py

.PHONY: confirm
confirm: ## Run every decision record's confirmation command, once each
	# CI collects the pytest ones instead, because the job has just run the
	# whole suite (OPS-0002). Here they execute.
	python3 scripts/run-confirmations.py

.PHONY: gen
gen: ## Regenerate the decision index and Cursor rules
	python3 scripts/gen-decisions.py

.PHONY: smoke
smoke: ## One real call through the gateway, under a cent
	$(UV) python scripts/smoke.py

.PHONY: providers
providers: ## One tiny real call per model: reachable, not merely resolvable
	$(UV) python scripts/probe_providers.py

.PHONY: persona-probe
persona-probe: ## Does sampling Jev preserve persona? 280 live calls, ~half a cent
	$(UV) python scripts/persona_probe.py

.PHONY: spend
spend: ## What has been spent so far — from the table, not the checkpoint
	@$(UV) python -c "from jeve.llm.ledger import SpendLedger; import json; s = SpendLedger().read(); print(json.dumps({'effective_usd': round(s.effective_usd, 6), 'settled_usd': round(s.settled_usd, 6), 'reserved_usd': round(s.reserved_usd, 6), 'calls': s.calls, 'baseline_usd': s.baseline_usd, 'remote_usd': s.remote_usd}, indent=2))" 2>/dev/null || (test -f ops/spend.json && cat ops/spend.json || echo '{"effective_usd": 0}')

.PHONY: db-up
db-up: ## Start Postgres and apply migrations
	docker compose up -d --wait
	npx nx run py:sync
	cd py && uv run python -c "from jeve import db; print('applied:', db.migrate() or 'nothing')"

.PHONY: db-down
db-down: ## Stop Postgres, keep the data
	docker compose down

.PHONY: fixture
fixture: ## Run the golden fixture. POLICY=jev|rules CALLS=replay|record
	npx nx run sim:fixture --args="$(if $(POLICY),--policy $(POLICY)) $(if $(CALLS),--calls $(CALLS)) $(if $(DAYS),--days $(DAYS))"

.PHONY: soak
soak: ## 35 sim-days on rules, on its own database; checks invariants, writes ops/soak.md. POLICY= CALLS= DAYS= COUNTERFACTUAL=1
	$(UV) python scripts/soak.py $(if $(POLICY),--policy $(POLICY)) $(if $(CALLS),--calls $(CALLS)) $(if $(DAYS),--days $(DAYS)) $(if $(COUNTERFACTUAL),--counterfactual)

.PHONY: sim
sim: ## The ever-running world: Jev live, paced, budget-governed, restart-safe
	npx nx run sim:run --args="--calls $(or $(CALLS),record) $(if $(POLICY),--policy $(POLICY)) --verbose"

.PHONY: sim-stop
sim-stop: ## Ask the daemon to stop at the end of its current tick
	-pkill -TERM -f "jeve.sim" && echo "asked it to stop" || echo "no daemon running"

.PHONY: api
api: ## Run the API on :8000
	npx nx run api:start

.PHONY: contracts
contracts: ## Generate zod contracts from pydantic models
	npx nx run contracts:generate

.PHONY: contracts-check
contracts-check: ## Check if generated contracts are in sync with pydantic models
	npx nx run contracts:check-drift

.PHONY: docker-build
docker-build: ## Build all Docker images
	docker build -f infra/docker/Dockerfile.web -t jeve-web .
	docker build -f infra/docker/Dockerfile.api -t jeve-api .
	docker build -f infra/docker/Dockerfile.sim -t jeve-sim .

.PHONY: docker-up
docker-up: ## Start production stack with Docker Compose
	docker-compose -f docker-compose.prod.yml up -d

.PHONY: docker-down
docker-down: ## Stop production stack
	docker-compose -f docker-compose.prod.yml down

.PHONY: docker-logs
docker-logs: ## View production stack logs
	docker-compose -f docker-compose.prod.yml logs -f

.PHONY: deploy-web
deploy-web: ## Deploy web app to Cloudflare Workers (builds first: NEXT_PUBLIC_* is inlined)
	cd apps/web && NEXT_PUBLIC_JEVE_API=https://jeve-api.punitarani.com pnpm exec next build && wrangler deploy

.PHONY: deploy-api
deploy-api: ## Deploy API to Fly.io
	fly deploy --config fly.toml --process-groups api

.PHONY: deploy-sim
deploy-sim: ## Deploy simulation worker to Fly.io
	fly deploy --config fly.toml --process-groups sim

.PHONY: deploy
deploy: deploy-web deploy-api deploy-sim ## Deploy all services

.PHONY: e2e
e2e: ## Full stack from a clean checkout, plus the economics report
	./scripts/e2e.sh
