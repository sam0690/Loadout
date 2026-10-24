# Local stack. `make up` starts everything, `make down` stops it.
#
# Postgres and Redis run in docker compose; the API, the plan worker and the web app run
# on the host. Ports come from .env (copy .env.example), so a machine where 5433 is taken
# changes .env, not this file.
#
# Host processes run in the background, each in its own process group (setsid), with a
# pid file and a log in .run/. Killing the group, not just the pid, is what stops the
# children too -- `uv run` and `next` each leave a second process behind otherwise.

SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -eu -o pipefail -c

include .env
export

API_PORT ?= 8001
WEB_PORT ?= 3000
RUN := .run

.PHONY: up down db db-down migrate seed api worker web status logs test e2e

up: db migrate api worker web ## Start the whole stack
	@echo "Web http://localhost:$(WEB_PORT)  API http://localhost:$(API_PORT)/docs  Logs: make logs"

down: ## Stop the whole stack (data is kept)
	@for name in web worker api; do \
		if [ -f $(RUN)/$$name.pid ]; then \
			kill -- -$$(cat $(RUN)/$$name.pid) 2>/dev/null && echo "stopped $$name" || true; \
			rm -f $(RUN)/$$name.pid; \
		fi; \
	done
	@docker compose stop

db: ## Postgres and Redis, waiting until healthy
	@docker compose up -d --wait

db-down:
	@docker compose stop

migrate: db
	@uv run alembic upgrade head

seed: migrate ## Catalog, graph, archetypes and exercise media. Once, or after seed changes
	@uv run python -m ingest

# start NAME COMMAND...: run in the background unless already running.
define start
	@mkdir -p $(RUN)
	@if [ -f $(RUN)/$(1).pid ] && kill -0 $$(cat $(RUN)/$(1).pid) 2>/dev/null; then \
		echo "$(1) already running"; \
	else \
		setsid nohup $(2) > $(RUN)/$(1).log 2>&1 < /dev/null & echo $$! > $(RUN)/$(1).pid; \
		echo "started $(1) (log: $(RUN)/$(1).log)"; \
	fi
endef

api:
	$(call start,api,uv run uvicorn api.main:app --port $(API_PORT))

worker:
	$(call start,worker,uv run python -m worker)

# The dev server: hot reload, no build step. `cd web && npm run build && npm start` for
# the production build (the service worker and offline behave as shipped).
web:
	$(call start,web,env NEXT_TELEMETRY_DISABLED=1 NEXT_PUBLIC_API_URL=http://localhost:$(API_PORT) npm --prefix web run dev -- -p $(WEB_PORT))

status: ## What is running
	@for name in api worker web; do \
		if [ -f $(RUN)/$$name.pid ] && kill -0 $$(cat $(RUN)/$$name.pid) 2>/dev/null; then \
			echo "$$name: running (pid $$(cat $(RUN)/$$name.pid))"; \
		else echo "$$name: stopped"; fi; \
	done
	@docker compose ps --format '{{.Service}}: {{.Status}}'

logs: ## Follow every log
	@tail -n 20 -F $(RUN)/*.log

test: db ## Backend and web unit tests
	@uv run pytest -q
	@npm --prefix web test

e2e: ## Playwright against the running stack (make up first)
	@cd web && API_URL=http://localhost:$(API_PORT) API_LOG=$(CURDIR)/$(RUN)/api.log npx playwright test
