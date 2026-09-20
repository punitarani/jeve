# jeve — one command per thing.
.DEFAULT_GOAL := help
SHELL := /bin/bash
ROOT := $(shell pwd)

# A clean clone has no .env, and `uv run --env-file` hard-errors on a missing
# file. Replay and every offline check must work without credentials.
ENVFILE := $(if $(wildcard $(ROOT)/.env),--env-file $(ROOT)/.env,)
UV := uv run --directory $(ROOT)/py $(ENVFILE)

.PHONY: help
help: ## Show this
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[1m%-12s\033[0m %s\n", $$1, $$2}'

.PHONY: check
check: lint types test decisions ## Everything that must pass, offline

.PHONY: lint
lint: ## ruff check + format check
	cd py && uv run ruff check .
	cd py && uv run ruff format --check .

.PHONY: types
types: ## mypy --strict
	cd py && uv run mypy

.PHONY: test
test: ## pytest, no network
	cd py && uv run pytest

.PHONY: decisions
decisions: ## Validate records; fail if generated artifacts are stale
	python3 scripts/gen-decisions.py --check
	python3 scripts/test_gen_decisions.py

.PHONY: gen
gen: ## Regenerate the decision index and Cursor rules
	python3 scripts/gen-decisions.py

.PHONY: smoke
smoke: ## One real call through the gateway, under a cent
	$(UV) python scripts/smoke.py

.PHONY: spend
spend: ## What has been spent so far
	@test -f ops/spend.json && cat ops/spend.json || echo '{"effective_usd": 0}'

.PHONY: db-up
db-up: ## Start Postgres and apply migrations
	docker compose up -d --wait
	cd py && uv run python -c "from jeve import db; print('applied:', db.migrate() or 'nothing')"

.PHONY: db-down
db-down: ## Stop Postgres, keep the data
	docker compose down

.PHONY: fixture
fixture: ## Run the golden fixture on rules only (free, no network)
	$(UV) python scripts/run_fixture.py
