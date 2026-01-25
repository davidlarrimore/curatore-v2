SHELL := /bin/sh

.PHONY: up down ps logs

# Build profile flags based on environment variables
# ENABLE_DOCLING_SERVICE=true adds --profile docling
# USE_OBJECT_STORAGE=true adds --profile minio
define get_profiles
$(if $(filter true,$(ENABLE_DOCLING_SERVICE)),--profile docling) $(if $(filter true,$(USE_OBJECT_STORAGE)),--profile minio)
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
	@if [ "$(ENABLE_DOCLING_SERVICE)" = "true" ]; then \
		echo "  📄 Docling:     http://localhost:5151"; \
	fi
	@if [ "$(USE_OBJECT_STORAGE)" = "true" ]; then \
		echo "  💾 Storage:     http://localhost:8020"; \
		echo "  🪣 MinIO:       http://localhost:9001"; \
	fi

down:
	@echo "Stopping stack (including all profiles if present)..."
	-docker compose --profile docling --profile minio down --remove-orphans
	-docker compose down --remove-orphans

ps:
	docker compose ps

logs:
	docker compose logs -f
