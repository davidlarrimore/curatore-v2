SHELL := /bin/sh

ENGINE_SCRIPT := ./scripts/extraction-engines.sh

.PHONY: up down ps logs

up:
	@engines="$$(bash $(ENGINE_SCRIPT) list)"; \
	extras="$$(bash $(ENGINE_SCRIPT) extras)"; \
	profiles=""; \
	for eng in $$extras; do \
		profiles="$$profiles --profile $$eng"; \
	done; \
	echo "Starting Curatore (extraction engines: $$engines)"; \
	docker compose $$profiles up -d --build

down:
	@engines="$$(bash $(ENGINE_SCRIPT) list)"; \
	extras="$$(bash $(ENGINE_SCRIPT) extras)"; \
	profiles=""; \
	for eng in $$extras; do \
		profiles="$$profiles --profile $$eng"; \
	done; \
	echo "Stopping Curatore (extraction engines: $$engines)"; \
	if [ -n "$$profiles" ]; then \
		docker compose $$profiles down --remove-orphans || true; \
	fi; \
	docker compose down --remove-orphans || true

ps:
	docker compose ps

logs:
	docker compose logs -f
