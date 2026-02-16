# CLAUDE.md — Curatore Backend

> **Note:** This repo (curatore-v2) is the development fork of curatore-backend. Keep this CLAUDE.md in sync with `curatore-localdev/curatore-backend/CLAUDE.md`.

FastAPI backend for Curatore: document processing, full-text search, LLM analysis, and workflow automation.

## Key Commands

```bash
backend/.venv/bin/python -m pytest backend/tests -v   # Run tests (local venv)
docker exec curatore-backend alembic upgrade head       # Run migrations
docker exec curatore-backend alembic revision --autogenerate -m "description"  # New migration
docker exec curatore-backend python -m app.core.commands.seed --create-admin   # Seed admin
./scripts/tail_worker.sh                                # Worker logs
./scripts/queue_health.sh                               # Queue health
```

## File Navigation

| When you need to... | Look in... |
|---------------------|------------|
| Add/modify an API endpoint | `app/api/v1/{admin,data,ops,cwr}/routers/` |
| Add/modify Pydantic request/response models | `app/api/v1/{namespace}/schemas.py` or `app/core/models/` |
| Add/modify a Celery background task | `app/core/tasks/{extraction,sam,salesforce,sharepoint,scrape,procedures,forecasts,maintenance}.py` |
| Add/modify a CWR function | `app/cwr/tools/primitives/<category>/` or `app/cwr/tools/compounds/` |
| Modify CWR procedure generation | `app/cwr/procedures/compiler/ai_generator.py` + `context_builder.py` |
| Add/modify tool contracts | `app/cwr/tools/base.py` (FunctionMeta) + `app/cwr/contracts/` |
| Add/modify governance profiles | `app/cwr/governance/` |
| Work with external service adapters | `app/connectors/adapters/` (ServiceAdapter ABC + implementations) |
| Work with SAM.gov integration | `app/connectors/sam_gov/` |
| Work with forecast integrations | `app/connectors/{gsa_gateway,dhs_apfs,state_forecast}/` |
| Work with Salesforce/SharePoint | `app/connectors/{salesforce,sharepoint}/` |
| Work with web scraping | `app/connectors/scrape/` |
| Work with search/indexing/embeddings | `app/core/search/` |
| Work with metadata registry/facets | `app/core/metadata/` + `app/core/metadata/registry/*.yaml` |
| Work with assets/runs/events | `app/core/shared/` |
| Work with object storage | `app/core/storage/` |
| Work with auth/connections/email | `app/core/auth/` |
| Work with LLM routing/generation | `app/core/llm/` |
| Work with queues/scheduling | `app/core/ops/` |
| Work with document ingestion | `app/core/ingestion/` |
| Modify startup sequence | `app/main.py` (lifespan) + `app/core/commands/prestart.py` |
| Work with database models | `app/core/database/models/` |
| Modify FastAPI dependencies | `app/dependencies.py` |
| Work with config loading | `app/core/shared/config_loader.py` + `app/config.py` (Settings) |

## Architecture Rules

1. **Extraction is infrastructure** — Automatic on upload, not per-workflow
2. **Assets are first-class** — Documents tracked with version history and provenance
3. **Run-based execution** — All processing tracked via Run records with structured logs
4. **Database is source of truth** — Object store contains only bytes
5. **Queue isolation** — Each job type has its own Celery queue to prevent blocking
6. **Contract-constrained governance** — Functions expose JSON Schema contracts with side-effect declarations, payload profiles, and exposure policies
7. **Config is required, not optional** — `config.yml` validated at startup with fail-fast; no silent fallbacks

### Configuration Convention

See [Configuration](docs/CONFIGURATION.md) for full reference.

- **`.env`** — Infrastructure & secrets: credentials, Docker endpoints (Redis, MinIO, PostgreSQL), dev toggles
- **`config.yml`** — Application behavior: feature flags, LLM models/routing, external service discovery, search tuning, queue behavior
- Secrets go in `.env`, referenced by `config.yml` via `${VAR_NAME}` syntax
- Infrastructure endpoints (Redis, MinIO, PostgreSQL) → `.env`
- External service discovery (Document Service, Playwright, LLM) → `config.yml`
- **Never add hardcoded model fallbacks** — if config is wrong, fail visibly
- **Legacy debt:** `app/config.py` Settings class has ~40 fields superseded by config.yml — harmless, will shrink as services extract

### Service Breakout Pattern

When a service moves to its own repo (as Playwright and Document Service already have):
1. Remove its Docker config from `.env`
2. Keep discovery settings in `config.yml`
3. Use `connectors/adapters/` `ServiceAdapter` pattern with 3-tier config resolution

## Auth & Org Context

See [Auth & Access Model](docs/AUTH_ACCESS_MODEL.md) for full reference.

**Critical dependency functions** (`app/dependencies.py`):

| Dependency | Returns | Use when... |
|-----------|---------|-------------|
| `get_effective_org_id` | `Optional[UUID]` | Cross-org admin views (returns `None` for admin system context) |
| `get_current_org_id` | `UUID` (required) | Org-scoped operations (raises 400 if no org context) |
| `get_user_org_ids` | `List[UUID]` | CWR multi-org scoping (all orgs user can access) |
| `require_admin` | `User` | System admin only endpoints |

**Rules:**
1. Admin users have `organization_id=NULL` — **never** use `current_user.organization_id` directly
2. Non-admin users access orgs via `user_organization_memberships` table (no primary org concept)
3. System org (`__system__`) is for CWR procedure ownership only, never for user assignment
4. CWR function visibility is filtered by org's enabled data sources
5. Generation profiles are server-enforced by role (`admin` → `admin_full`, `member` → `workflow_standard`)

## Patterns to Follow

### New API Endpoint
1. Create router in the appropriate namespace (`admin/`, `data/`, `ops/`, or `cwr/`)
2. Add Pydantic models to the namespace's `schemas.py`
3. Implement service in the appropriate `app/core/` subdirectory
4. Register router in the namespace's `__init__.py`
5. Update frontend API client in [curatore-frontend](https://github.com/Amivero-LLC/curatore-frontend) `lib/api.ts`

### New Celery Task
1. Add task to the appropriate module in `app/core/tasks/`
2. Use `@celery_app.task(name="app.tasks.module.my_task")`
3. Re-export from `app/core/tasks/__init__.py` for backward compatibility
4. Create Run record for tracking

### New CWR Function
1. Create function module in `app/cwr/tools/primitives/<category>/` (or `compounds/` for multi-step)
2. Define `FunctionMeta` with governance fields (`side_effects`, `payload_profile`, `exposure_profile`, etc.)
3. Define `input_schema` and `output_schema` as JSON Schema dicts directly on `FunctionMeta`
4. Register in `app/cwr/tools/registry.py`
5. Contract is auto-derived via `FunctionMeta.as_contract()`

### New Database Migration
1. Create migration: `docker exec curatore-backend alembic revision --autogenerate -m "description"`
2. **Parity rule:** If the migration INSERTs reference data or creates SQL VIEWs, you **MUST** also update `_create_all_tables()` in `app/core/commands/prestart.py` to maintain parity with the fresh install path
3. Test both paths: existing DB (`alembic upgrade head`) and fresh install

### New Service
Place in the correct location:
- **CWR code** (functions, procedures, pipelines, contracts, governance) → `app/cwr/`
- **Connectors** (external data integrations) → `app/connectors/`
- **Auth/identity** → `app/core/auth/`
- **Ingestion/extraction** → `app/core/ingestion/`
- **LLM** → `app/core/llm/`
- **Queues/scheduling** → `app/core/ops/`
- **Search/indexing** → `app/core/search/`
- **Cross-cutting** (assets, runs, events, storage, config) → `app/core/shared/`

### New Queue Type
See [Queue System - Adding New Queue Types](docs/QUEUE_SYSTEM.md#adding-new-queue-types)

### New Data Integration
See [Data Connections Guide](docs/DATA_CONNECTIONS.md)

## Anti-Patterns & Gotchas

1. **NEVER** use `current_user.organization_id` directly — admin users have `NULL`. Use the dependency functions above.
2. **NEVER** hardcode LLM model names — always read from `config.yml` via config loader. No fallback defaults.
3. **NEVER** add silent config fallbacks — if config is missing, fail with a clear error at startup.
4. **NEVER** commit `.env` files — they contain secrets.
5. **NEVER** use `localhost` for inter-service URLs in Docker — use container names (e.g., `http://document-service:8010`). `localhost` is for browser/developer access only.
6. **NEVER** assign users to the `__system__` org — it's for CWR procedure ownership only.
7. **NEVER** skip the Run record — all background processing must create a Run for tracking.
8. **NEVER** add a migration that creates reference data/VIEWs without updating `prestart.py` — fresh installs will be out of sync.
9. **NEVER** put external service discovery in `.env` — Document Service, Playwright, LLM URLs go in `config.yml`.
10. **NEVER** import from `connectors/` in `core/` — connectors depend on core, not the reverse.
11. **NEVER** create a Celery task without re-exporting from `app/core/tasks/__init__.py`.
12. **Metadata namespaces** — search chunk metadata uses nested JSONB namespaces (`source`, `sharepoint`, `sam`, `salesforce`, `forecast`, `custom`). Don't flatten them.
13. **Facet filters vs metadata filters** — prefer `facet_filters` (cross-domain, resolved by registry) over raw `metadata_filters` (JSONB containment). See [Search & Indexing](docs/SEARCH_INDEXING.md).
14. **Three containers, one image** — backend, worker, and beat all run from the same Docker image. Changes to app code affect all three.
15. **Celery task names** — must follow `app.tasks.module.task_name` pattern for backward compatibility.

## Testing

```bash
# Run all tests
backend/.venv/bin/python -m pytest backend/tests -v

# Run specific test file
backend/.venv/bin/python -m pytest backend/tests/test_specific.py -v

# Inside container
docker exec curatore-backend python -m pytest tests -v
```

- Tests skip when optional dependencies are missing
- Use `monkeypatch` for env var testing
- Create fixtures for database sessions and test data

## Configuration Consistency Checklist

When modifying service adapter configuration:
- [ ] `config.yml` has the service discovery entry
- [ ] `app/config.py` Settings class doesn't conflict (legacy fields)
- [ ] `app/core/shared/config_loader.py` loads the new config correctly
- [ ] `app/main.py` startup sequence validates the new config
- [ ] `prestart.py` handles the dependency correctly if it's required at boot

## Deep Reference Docs

| Document | Description |
|----------|-------------|
| [Search & Indexing](docs/SEARCH_INDEXING.md) | Hybrid search, pgvector, chunking, embeddings, reindexing |
| [Metadata Catalog](docs/METADATA_CATALOG.md) | Namespaces, fields, facets, reference data, registry service |
| [Queue System](docs/QUEUE_SYSTEM.md) | Queue architecture, job groups, cancellation |
| [Functions & Procedures](docs/FUNCTIONS_PROCEDURES.md) | Workflow automation, CWR functions reference |
| [Document Processing](docs/DOCUMENT_PROCESSING.md) | Extraction pipeline |
| [Data Connections](docs/DATA_CONNECTIONS.md) | Adding new integrations |
| [SAM.gov Integration](docs/SAM_INTEGRATION.md) | SAM.gov data model and API |
| [Salesforce Integration](docs/SALESFORCE_INTEGRATION.md) | Salesforce CRM integration |
| [SharePoint Integration](docs/SHAREPOINT_INTEGRATION.md) | SharePoint folder sync |
| [Forecast Integration](docs/FORECAST_INTEGRATION.md) | Acquisition forecast sources |
| [Configuration](docs/CONFIGURATION.md) | Environment and YAML config reference |
| [Auth & Access Model](docs/AUTH_ACCESS_MODEL.md) | Roles, org context, RBAC, dependencies |
| [Maintenance Tasks](docs/MAINTENANCE_TASKS.md) | Scheduled background tasks |
| [API Documentation](docs/API_DOCUMENTATION.md) | Complete API reference (also at `/docs`) |
| [MCP Gateway](https://github.com/davidlarrimore/curatore-mcp-service) | AI tool server (external service) |
| [Frontend](https://github.com/Amivero-LLC/curatore-frontend) | Next.js frontend (separate repo) |
