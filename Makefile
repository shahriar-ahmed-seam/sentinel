.DEFAULT_GOAL := help
API := services/gateway
WEB := web
PY ?= python

.PHONY: help
help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-16s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Install gateway + console dependencies
	$(PY) -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -r $(API)/requirements.txt ruff==0.8.4
	cd $(WEB) && npm ci --no-audit --no-fund

.PHONY: otel
otel: ## Add the optional OTLP exporter to the venv
	.venv/bin/pip install -r $(API)/requirements-optional.txt

.PHONY: api
api: ## Run the gateway on :8000
	cd $(API) && uvicorn sentinel.main:app --reload --port 8000

.PHONY: web
web: ## Run the console on :3000
	cd $(WEB) && npm run dev

.PHONY: lint
lint: ## Lint and type-check both services
	cd $(API) && ruff check . && ruff format --check .
	cd $(WEB) && npm run lint && npx tsc --noEmit

.PHONY: fmt
fmt: ## Auto-format the gateway
	cd $(API) && ruff format . && ruff check --fix .

.PHONY: build
build: ## Production build of the console
	cd $(WEB) && npm run build

.PHONY: up
up: ## Full stack: postgres, gateway, console, prometheus, grafana, otel, jaeger
	docker compose up --build

.PHONY: down
down: ## Stop the stack
	docker compose down

.PHONY: nuke
nuke: ## Stop the stack and delete volumes
	docker compose down -v

.PHONY: demo
demo: ## Exercise routing, cache, failover, tracing and a load ramp
	$(PY) scripts/demo.py --base-url $${BASE_URL:-http://localhost:8000}

.PHONY: reset
reset: ## Delete local SQLite state
	rm -rf .data

.PHONY: images
images: ## Build both container images locally
	docker build -t sentinel-gateway:local $(API)
	docker build -t sentinel-web:local $(WEB)
