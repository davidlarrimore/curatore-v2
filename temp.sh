docker compose build --no-cache extraction-service
docker compose up -d --force-recreate extraction-service

# Sanity: ensure module imports and has the functions
docker exec -it curatore-extraction python - <<'PY'
import importlib
m = importlib.import_module("app.services.extraction_service")
print("OK:", hasattr(m, "extract_markdown"), hasattr(m, "extraction_service"))
PY
