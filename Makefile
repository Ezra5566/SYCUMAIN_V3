# Developer entry points for SYCUMAIN V3.
#
#   make help          list the targets
#   make check         every gate that CI runs, locally
#
# The development stack and the production stack are separate files on purpose:
# see docs/deployment-v3.md.

SHELL := /bin/bash
ROOT := $(shell pwd)
WEB := $(ROOT)/apps/web
API := $(ROOT)/apps/api
API_PY := $(API)/.venv/bin/python
COMPOSE_DEV := docker compose -f docker-compose.yml
PROD_ENV ?= .env.production
COMPOSE_PROD := docker compose --env-file $(PROD_ENV) -f docker-compose.prod.yml

.DEFAULT_GOAL := help

.PHONY: help
help: ## list the targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- Development stack ------------------------------------------------------
.PHONY: up
up: ## start the development stack (web 3101, api 8001, db 5435)
	$(COMPOSE_DEV) up -d --build
	@echo "web:  http://localhost:3101"
	@echo "api:  http://localhost:8001/api/v1/health"

.PHONY: down
down: ## stop the development stack (keeps its data)
	$(COMPOSE_DEV) down

.PHONY: logs
logs: ## follow development logs
	$(COMPOSE_DEV) logs -f --tail=100

# --- Backend ----------------------------------------------------------------
.PHONY: test-api
test-api: ## run the backend suite against the disposable test database
	cd $(API) && ./.venv/bin/python -m pytest -q

.PHONY: lint-api
lint-api: ## lint the backend
	cd $(API) && ./.venv/bin/python -m ruff check app tests tools

.PHONY: migrate
migrate: ## apply migrations to the development database
	$(COMPOSE_DEV) exec api python -m alembic upgrade head

.PHONY: migrate-check
migrate-check: ## fail when models and migrations disagree
	$(COMPOSE_DEV) exec api python -m alembic check

# --- Frontend ---------------------------------------------------------------
.PHONY: typecheck
typecheck: ## typecheck the web app
	cd $(WEB) && npx tsc --noEmit

.PHONY: lint
lint: ## lint the web app
	cd $(WEB) && npx next lint

.PHONY: build
build: ## production build of the web app
	cd $(WEB) && npx next build

.PHONY: i18n
i18n: ## translation parity across all five locales
	cd $(WEB) && node scripts/check-i18n.mjs

.PHONY: locales
locales: ## verify all five locale routes and Arabic RTL against a production build
	cd $(WEB) && pnpm check:locales

# --- Browser ----------------------------------------------------------------
.PHONY: e2e
e2e: ## browser suite against an isolated, disposable stack
	./scripts/e2e.sh

# --- Production -------------------------------------------------------------
.PHONY: prod-config
prod-config: ## validate the production composition resolves
	$(COMPOSE_PROD) config >/dev/null && echo "production composition is valid"

.PHONY: prod-build
prod-build: ## build the production images
	$(COMPOSE_PROD) build

.PHONY: prod-migrate
prod-migrate: ## explicit migration step (never runs on container start)
	$(COMPOSE_PROD) --profile tools run --rm migrate

.PHONY: prod-up
prod-up: ## start the production stack behind TLS
	$(COMPOSE_PROD) up -d

.PHONY: backup
backup: ## dump the production database and document store
	COMPOSE_FILE=docker-compose.prod.yml COMPOSE_PROJECT=$${COMPOSE_PROJECT:-sycumain-v3-prod} \
		./scripts/backup.sh

.PHONY: restore-verify
restore-verify: ## restore the latest backup into a scratch database and check it
	COMPOSE_FILE=docker-compose.prod.yml COMPOSE_PROJECT=$${COMPOSE_PROJECT:-sycumain-v3-prod} \
		./scripts/restore.sh latest

# --- Aggregate --------------------------------------------------------------
.PHONY: check
check: typecheck i18n migrate-check ## every fast gate CI runs
	@echo "all fast checks passed"
