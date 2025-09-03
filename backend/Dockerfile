# ============================================================================
# Curatore v2 - Backend/Worker Dockerfile
# Build context: ./backend
# ----------------------------------------------------------------------------
# NOTE:
# - Because the build context is ./backend (see docker-compose.yml),
#   all COPY paths must be relative to ./backend, e.g.:
#     COPY requirements.txt /app/requirements.txt
#     COPY app /app/app
# ============================================================================

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (add/remove as needed for OCR/PDF/image support)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ghostscript \
    poppler-utils \
    tesseract-ocr \
 && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# App source (relative to build context ./backend)
COPY app /app/app

# NOTE: do NOT create /app/files here; it's supplied by bind mount (./files -> /app/files)

EXPOSE 8000

# Default entrypoint is set by compose (uvicorn for backend, celery for worker)
