SHELL := /bin/sh

.PHONY: up down ps logs

up:
	@if [ "$(ENABLE_DOCLING_SERVICE)" = "true" ]; then \
		echo "Starting with Docling profile (detached)..."; \
		docker compose --profile docling up -d --build; \
	else \
		echo "Starting without Docling (detached)..."; \
		docker compose up -d --build; \
	fi

down:
	@echo "Stopping stack (including docling if present)..."
	- docker compose --profile docling down --remove-orphans
	- docker compose down --remove-orphans

ps:
	docker compose ps

logs:
	docker compose logs -f
