SHELL := /bin/sh

.PHONY: up down ps logs

# Build profile flags based on environment variables
# ENABLE_POSTGRES_SERVICE=true adds --profile postgres (default: true)
# ENABLE_DOCLING_SERVICE=true adds --profile docling
define get_profiles
$(if $(or $(filter true,$(ENABLE_POSTGRES_SERVICE)),$(if $(ENABLE_POSTGRES_SERVICE),,true)),--profile postgres) $(if $(filter true,$(ENABLE_DOCLING_SERVICE)),--profile docling)
endef

up:
	@PROFILES="$(strip $(call get_profiles))"; \
	if [ -n "$$PROFILES" ]; then \
		echo "Starting with profiles:$$PROFILES (detached)..."; \
		docker compose $$PROFILES up -d --build; \
	else \
		echo "Starting without optional profiles (detached)..."; \
		docker compose up -d --build; \
	fi
	@echo ""
	@echo "Services started:"
	@echo "  🌐 Frontend:    http://localhost:3000"
	@echo "  🔗 Backend:     http://localhost:8000"
	@echo "  📦 Extraction:  http://localhost:8010"
	@echo "  🤖 MCP Gateway: http://localhost:8020"
	@echo "  🪣 MinIO:       http://localhost:9001"
	@if [ "$(ENABLE_POSTGRES_SERVICE)" = "true" ] || [ -z "$(ENABLE_POSTGRES_SERVICE)" ]; then \
		echo "  🐘 PostgreSQL:  localhost:5432"; \
	fi
	@if [ "$(ENABLE_DOCLING_SERVICE)" = "true" ]; then \
		echo "  📄 Docling:     http://localhost:5151"; \
	fi

down:
	@echo "Stopping stack (including all profiles if present)..."
	-docker compose --profile postgres --profile docling down --remove-orphans
	-docker compose down --remove-orphans

ps:
	docker compose ps

logs:
	docker compose logs -f
