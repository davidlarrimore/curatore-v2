# Curatore v2 Configuration Guide

## Overview

Curatore v2 supports two configuration methods:
1. **YAML Configuration** (recommended): `config.yml` at project root
2. **Environment Variables** (legacy): `.env` file

**Configuration Priority:**
1. config.yml (if present)
2. Environment variables from .env
3. Built-in defaults

---

## Getting Started

### Quick Start

1. Copy the example configuration:
   ```bash
   cp config.yml.example config.yml
   ```

2. Edit `config.yml` with your service credentials

3. Validate your configuration:
   ```bash
   python -m app.commands.validate_config
   ```

4. Start the application:
   ```bash
   docker-compose up -d
   ```

### Migrating from .env

If you have an existing `.env` file:

```bash
python scripts/migrate_env_to_yaml.py
```

This generates `config.yml` from your `.env` settings with proper structure and ${VAR_NAME} references for secrets.

---

## Configuration Reference

### LLM Service

Configure your Language Model provider for document evaluation.

**Required:**
- `llm.provider`: Provider name (openai, ollama, openwebui, lmstudio)
- `llm.api_key`: API key or authentication token
- `llm.base_url`: API endpoint URL
- `llm.model`: Model identifier

**Optional:**
- `llm.timeout`: Request timeout in seconds (default: 60)
- `llm.max_retries`: Maximum retry attempts (default: 3)
- `llm.temperature`: Generation temperature (default: 0.7)
- `llm.verify_ssl`: Verify SSL certificates (default: true)
- `llm.options`: Provider-specific options (dict)

**Examples:**

OpenAI:
```yaml
llm:
  provider: openai
  api_key: ${OPENAI_API_KEY}
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
```

Ollama (local):
```yaml
llm:
  provider: ollama
  api_key: not-required
  base_url: http://localhost:11434/v1
  model: llama2
  timeout: 120
```

---

### Document Service

Configure the standalone Document Service for document extraction.

The backend delegates all extraction to the Document Service, which handles triage and engine selection internally (fast_pdf, markitdown, docling). The backend connects via the `DocumentServiceAdapter` using 3-tier config resolution: DB Connection → config.yml → environment variables.

**Engine Configuration:**
- `name`: Engine identifier
- `engine_type`: `document-service`
- `service_url`: Document Service endpoint URL
- `enabled`: Enable/disable (default: true)
- `timeout`: Request timeout in seconds (default: 300)
- `verify_ssl`: Verify SSL certificates (default: true)

**Environment Variables (fallback):**
- `DOCUMENT_SERVICE_URL`: Document Service URL (e.g., `http://document-service:8010`)
- `DOCUMENT_SERVICE_API_KEY`: API key (optional)
- `DOCUMENT_SERVICE_TIMEOUT`: Request timeout in seconds (default: 300)
- `DOCUMENT_SERVICE_VERIFY_SSL`: Verify SSL (default: true)

**Example:**
```yaml
extraction:
  engines:
    - name: document-service
      engine_type: document-service
      service_url: http://document-service:8010
      timeout: 300
      enabled: true
```

> **Note:** Docling is configured inside the Document Service itself (via `DOCLING_SERVICE_URL`), not in the backend. The backend no longer communicates with Docling directly.

---

### Microsoft SharePoint

Configure SharePoint integration for document retrieval.

**Required:**
- `sharepoint.tenant_id`: Azure AD tenant ID (GUID)
- `sharepoint.client_id`: App registration client ID
- `sharepoint.client_secret`: App registration client secret

**Optional:**
- `sharepoint.enabled`: Enable SharePoint integration (default: true)
- `sharepoint.graph_scope`: OAuth scope (default: https://graph.microsoft.com/.default)
- `sharepoint.graph_base_url`: Graph API endpoint (default: https://graph.microsoft.com/v1.0)
- `sharepoint.timeout`: Request timeout in seconds (default: 60)
- `sharepoint.max_retries`: Maximum retry attempts (default: 3)

**Example:**
```yaml
sharepoint:
  enabled: true
  tenant_id: ${MS_TENANT_ID}
  client_id: ${MS_CLIENT_ID}
  client_secret: ${MS_CLIENT_SECRET}
  timeout: 60
```

---

### Email Service

Configure email delivery for user notifications.

**Required:**
- `email.backend`: Email backend (console, smtp, sendgrid, ses)
- `email.from_address`: From email address
- `email.from_name`: From display name

**SMTP Configuration (if backend=smtp):**
- `email.smtp.host`: SMTP server hostname
- `email.smtp.port`: SMTP server port (default: 587)
- `email.smtp.username`: SMTP authentication username
- `email.smtp.password`: SMTP authentication password
- `email.smtp.use_tls`: Use TLS encryption (default: true)
- `email.smtp.timeout`: Connection timeout in seconds (default: 30)

**Example:**
```yaml
email:
  backend: smtp
  from_address: noreply@curatore.app
  from_name: Curatore
  smtp:
    host: ${SMTP_HOST}
    port: 587
    username: ${SMTP_USERNAME}
    password: ${SMTP_PASSWORD}
    use_tls: true
```

---

### Storage Configuration

Configure file storage management.

**Optional (all have defaults):**

**Hierarchical Storage:**
- `storage.hierarchical`: Use organization-based structure (default: true)

**Deduplication:**
- `storage.deduplication.enabled`: Enable duplicate detection (default: true)
- `storage.deduplication.strategy`: Strategy (symlink, copy, reference, default: symlink)
- `storage.deduplication.hash_algorithm`: Hash algorithm (default: sha256)
- `storage.deduplication.min_file_size`: Minimum size to deduplicate in bytes (default: 1024)

**Retention:**
- `storage.retention.uploaded_days`: Days to retain uploaded files (default: 7)
- `storage.retention.processed_days`: Days to retain processed files (default: 30)
- `storage.retention.batch_days`: Days to retain batch files (default: 14)
- `storage.retention.temp_hours`: Hours to retain temp files (default: 24)

**Cleanup:**
- `storage.cleanup.enabled`: Enable automatic cleanup (default: true)
- `storage.cleanup.schedule_cron`: Cron schedule (default: "0 2 * * *")
- `storage.cleanup.batch_size`: Files per cleanup batch (default: 1000)
- `storage.cleanup.dry_run`: Dry-run mode (default: false)

**Example:**
```yaml
storage:
  hierarchical: true
  deduplication:
    enabled: true
    strategy: symlink
  retention:
    uploaded_days: 7
    processed_days: 30
  cleanup:
    enabled: true
    schedule_cron: "0 2 * * *"
```

---

### Queue Configuration

Configure Celery background job processing.

**Optional (all have defaults):**
- `queue.broker_url`: Redis URL for broker (default: redis://redis:6379/0)
- `queue.result_backend`: Redis URL for results (default: redis://redis:6379/1)
- `queue.default_queue`: Default queue name (default: processing)
- `queue.worker_concurrency`: Worker concurrency (default: 4)
- `queue.task_timeout`: Task timeout in seconds (default: 3600)

**Example:**
```yaml
queue:
  broker_url: redis://redis:6379/0
  result_backend: redis://redis:6379/1
  default_queue: processing
  worker_concurrency: 4
```

---

## Environment Variable References

You can reference environment variables in `config.yml` using `${VAR_NAME}` syntax:

```yaml
llm:
  api_key: ${OPENAI_API_KEY}  # Reads from .env or environment

sharepoint:
  tenant_id: ${MS_TENANT_ID}
  client_id: ${MS_CLIENT_ID}
  client_secret: ${MS_CLIENT_SECRET}
```

**Benefits:**
- Keep secrets in `.env` (not committed to Git)
- Share `config.yml` structure across environments
- Override specific values per environment

**Best Practices:**
- Reference all secrets via ${VAR_NAME}
- Store sensitive values only in .env
- Commit config.yml.example to Git
- Never commit config.yml or .env to Git

---

## Validation

Validate your configuration before starting:

```bash
python -m app.commands.validate_config

# Output:
✓ config.yml found and readable
✓ YAML syntax valid
✓ Schema validation passed
✓ Environment variables resolved
✓ LLM configuration valid
✓ Extraction configuration valid
✓ SharePoint configuration valid
✓ Email configuration valid
✓ All services reachable

Configuration is valid!
```

**Validation Checks:**
1. File exists and is readable
2. YAML syntax is valid
3. Schema validation passes (Pydantic models)
4. All ${VAR_NAME} references are set
5. Service connectivity (optional, use --skip-connectivity to disable)

---

## Troubleshooting

### Error: config.yml not found

**Solution:**
```bash
cp config.yml.example config.yml
# Edit config.yml with your settings
```

### Error: Invalid YAML syntax

**Cause:** YAML indentation or syntax error

**Solution:**
- Check YAML indentation (use spaces, not tabs)
- Validate YAML online: https://www.yamllint.com/
- Use validation command to see exact error

### Error: Missing environment variable

**Cause:** ${VAR_NAME} reference not found in .env or environment

**Solution:**
- Add missing variable to .env file
- Or replace ${VAR_NAME} with actual value in config.yml (not recommended for secrets)

### Error: Schema validation failed

**Cause:** Invalid configuration value or missing required field

**Solution:**
- Check validation error message for specific field
- Refer to configuration reference above
- Compare with config.yml.example

### Error: Service unreachable

**Cause:** Service URL incorrect or service not running

**Solution:**
- Verify URLs are correct and services are running
- Check Docker network connectivity
- Use --skip-connectivity flag to skip connectivity tests

---

## Migration from .env

### Automated Migration

Use the migration script to convert your .env to config.yml:

```bash
python scripts/migrate_env_to_yaml.py

# Output:
Reading .env file: .env
Found 25 environment variables

Generated config.yml with:
  ✓ LLM configuration (OpenAI)
  ✓ Extraction services (2 services)
  ✓ SharePoint configuration
  ✓ Email configuration (SMTP)
  ✓ Storage configuration
  ✓ Queue configuration

Successfully created config.yml
```

### Manual Migration

**Before (.env only):**
```bash
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
MS_TENANT_ID=...
MS_CLIENT_ID=...
```

**After (config.yml + .env):**

config.yml:
```yaml
llm:
  provider: openai
  api_key: ${OPENAI_API_KEY}  # From .env
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini

sharepoint:
  tenant_id: ${MS_TENANT_ID}  # From .env
  client_id: ${MS_CLIENT_ID}  # From .env
  client_secret: ${MS_CLIENT_SECRET}  # From .env
```

.env (secrets only):
```bash
OPENAI_API_KEY=sk-...
MS_TENANT_ID=...
MS_CLIENT_ID=...
MS_CLIENT_SECRET=...
```

---

## Advanced Topics

### Optional Services

All service configurations (llm, extraction, sharepoint, email) are optional. If not configured in config.yml, the system falls back to environment variables or disables the feature gracefully.

### Hot Reloading

Configuration is loaded once at service startup. To reload without restarting:

```python
from app.services.config_loader import config_loader
config_loader.reload()
```

### Multiple Environments

Use different config files per environment:

```bash
# Development
cp config.yml.example config.dev.yml
python -m app.commands.validate_config --config-path config.dev.yml

# Production
cp config.yml.example config.prod.yml
python -m app.commands.validate_config --config-path config.prod.yml

# Use environment-specific config
export CONFIG_PATH=config.prod.yml
docker-compose up -d
```

---

## Examples

### Complete Configuration

```yaml
version: "2.0"

llm:
  provider: openai
  api_key: ${OPENAI_API_KEY}
  base_url: https://api.openai.com/v1
  model: gpt-4o-mini
  timeout: 60
  max_retries: 3

extraction:
  engines:
    - name: document-service
      engine_type: document-service
      service_url: http://document-service:8010
      timeout: 300
      enabled: true

sharepoint:
  enabled: true
  tenant_id: ${MS_TENANT_ID}
  client_id: ${MS_CLIENT_ID}
  client_secret: ${MS_CLIENT_SECRET}

email:
  backend: smtp
  from_address: noreply@curatore.app
  from_name: Curatore
  smtp:
    host: ${SMTP_HOST}
    port: 587
    username: ${SMTP_USERNAME}
    password: ${SMTP_PASSWORD}
    use_tls: true

storage:
  hierarchical: true
  deduplication:
    enabled: true
    strategy: symlink
  retention:
    uploaded_days: 7
    processed_days: 30

queue:
  broker_url: redis://redis:6379/0
  result_backend: redis://redis:6379/1
  default_queue: processing
```

---

## Support

For questions or issues:

1. **Validation Command**: `python -m app.commands.validate_config`
2. **Migration Script**: `python scripts/migrate_env_to_yaml.py`
3. **Documentation**: This file and config.yml.example
4. **GitHub Issues**: Report bugs or request features
5. **Development Guide**: See CLAUDE.md for developer documentation

---

**Last Updated**: 2026-01-16

**Version**: Curatore v2.1.0 (Phase 9: YAML Configuration System)
