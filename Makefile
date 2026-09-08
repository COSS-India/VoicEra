SHELL := /bin/bash

COMPOSE  := docker compose
APP_FILE := docker-compose.yaml
MS_DIR   := model-server

# Extra arguments for a single invocation, e.g. `make up ARGS=--no-build`.
ARGS ?=

# Deferred on purpose, and expanded inside each recipe rather than when this
# file is parsed: the answer depends on model-server/.env and on whether an MPS
# daemon is running at the moment the target runs. Resolving it at parse time
# would freeze a list from before `make ms-setup` had written .env.
MS_COMPOSE = $(COMPOSE) $$(sh $(MS_DIR)/compose-files.sh) --project-directory $(MS_DIR)

.DEFAULT_GOAL := help

.PHONY: help up down restart logs ps \
        ms-setup ms-up ms-down ms-logs ms-ps \
        down-all \
        test test-providers test-api test-runtime test-model-server lint

# ---------------------------------------------------------------- application

application-up:  ## Start the application stack (generates missing secrets first)
	./scripts/start-application-services.sh $(ARGS)

application-down:  ## Stop the application stack (keeps volumes)
	./scripts/stop-application-services.sh $(ARGS)

restart: application-down application-up  ## Stop then start the application stack

application-logs:  ## Follow application logs (SERVICE=api to narrow)
	$(COMPOSE) -f $(APP_FILE) logs -f $(SERVICE)

application-ps:  ## Show application containers
	$(COMPOSE) -f $(APP_FILE) ps

# --------------------------------------------------------------- model-server

model-server-setup:  ## Configure slots, fetch weights, build and start model-server
	./scripts/start-model-server.sh

model-server-up:  ## Start model-server from the existing configuration
	$(MS_COMPOSE) up -d

model-server-down:  ## Stop model-server
	./scripts/stop-model-server.sh

model-server-logs:  ## Follow model-server logs
	$(MS_COMPOSE) logs -f

model-server-ps:  ## Show model-server containers
	$(MS_COMPOSE) ps

down-all: ## Stop both stacks
	-$(MAKE) application-down
	-$(MAKE) model-server-down

help:  ## Show this help	
	@echo "Voicera -- make targets"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "} {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
	@echo ""
