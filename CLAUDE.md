# CLAUDE.md

Development guidance for Claude Code working with Curatore v2.

## Quick Navigation

**Getting Started**: [Quick Start](#quick-start) | [Project Structure](#project-structure) | [Dev Commands](#development-commands)

**Core Systems**: [Architecture](#architecture-principles) | [Data Models](#key-data-models) | [Search & Indexing](docs/SEARCH_INDEXING.md) | [Metadata Catalog](docs/METADATA_CATALOG.md) | [Queue System](docs/QUEUE_SYSTEM.md)

**Workflows**: [Functions & Procedures](docs/FUNCTIONS_PROCEDURES.md) | [Tool Contracts](#tool-contracts--governance) | [Document Processing](docs/DOCUMENT_PROCESSING.md)

**Integrations**: [SAM.gov](docs/SAM_INTEGRATION.md) | [Salesforce](docs/SALESFORCE_INTEGRATION.md) | [SharePoint](docs/SHAREPOINT_INTEGRATION.md) | [Forecasts](docs/FORECAST_INTEGRATION.md) | [Web Scraping](docs/DATA_CONNECTIONS.md#web-scraping)

**AI Clients**: [MCP Gateway](mcp/README.md) | [Open WebUI](docs/MCP_OPEN_WEBUI.md)

**Reference**: [API Docs](docs/API_DOCUMENTATION.md) | [Configuration](docs/CONFIGURATION.md) | [Maintenance Tasks](docs/MAINTENANCE_TASKS.md)

---

## Project Overview

Curatore v2 is a document processing and curation platform that converts documents to Markdown, provides full-text search, and supports LLM-powered analysis.

### Tech Stack
- **Backend**: FastAPI (Python 3.12+), Celery workers, SQLAlchemy
- **Frontend**: Next.js 15.5, TypeScript, React 19, Tailwind CSS
- **Services**: Redis, MinIO/S3, Playwright, Document Service
- **Database**: PostgreSQL 16 with pgvector (required)

### Architecture Principles
1. **Extraction is infrastructure** - Automatic on upload, not per-workflow
2. **Assets are first-class** - Documents tracked with version history and provenance
3. **Run-based execution** - All processing tracked via Run records with structured logs
4. **Database is source of truth** - Object store contains only bytes
5. **Queue isolation** - Each job type has its own Celery queue to prevent blocking
6. **Contract-constrained governance** - Functions expose formal JSON Schema contracts with side-effect declarations, payload profiles, and exposure policies; the AI procedure generator uses these constraints when planning workflows

---

## Quick Start

```bash
# Start all services
./scripts/dev-up.sh

# Initialize storage buckets
./scripts/init_storage.sh

# Create admin user
docker exec curatore-backend python -m app.core.commands.seed --create-admin

# View logs
./scripts/dev-logs.sh
```

### URLs
| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |
| MCP Gateway | http://localhost:8020 |
| MinIO Console | http://localhost:9001 |
| PostgreSQL | localhost:5432 (curatore/curatore_dev_password) |

### Port Mappings
| Port | Service |
|------|---------|
| 3000 | Frontend |
| 5432 | PostgreSQL (with pgvector) |
| 8000 | Backend API |
| 8010 | Document Service |
| 8011 | Playwright Service |
| 8020 | MCP Gateway (AI tool server) |
| 6379 | Redis |
| 9000 | MinIO S3 API |
| 9001 | MinIO Console |

---

## Development Commands

```bash
# Backend tests (use venv)
backend/.venv/bin/python -m pytest backend/tests -v

# Frontend dev
cd frontend && npm run dev

# Worker logs
./scripts/tail_worker.sh

# Queue health
./scripts/queue_health.sh

# All tests
./scripts/run_all_tests.sh
```

---

## Project Structure

```
backend/
├── app/
│   ├── main.py                      # FastAPI entry point
│   ├── config.py                    # Settings
│   ├── celery_app.py                # Celery setup
│   ├── dependencies.py              # FastAPI DI
│   │
│   ├── api/v1/                      # REST API (4 namespaces)
│   │   ├── admin/routers/           # Auth, users, orgs, system, connections, api_keys
│   │   ├── data/routers/            # Assets, storage, search, metadata, connectors
│   │   ├── ops/routers/             # Runs, queue admin, metrics, websocket
│   │   └── cwr/routers/             # Functions, procedures, pipelines, contracts
│   │
│   ├── core/                        # Platform infrastructure
│   │   ├── database/                # SQLAlchemy engine, session, ORM models
│   │   ├── models/                  # Pydantic API/processing schemas
│   │   ├── utils/                   # Text utils, validators
│   │   ├── metadata/                # Metadata registry (YAML baseline + service)
│   │   ├── auth/                    # Auth, connections, email, password reset
│   │   ├── storage/                 # Object storage (MinIO/S3, paths, zip)
│   │   ├── search/                  # pg_search, pg_index, embeddings, chunking
│   │   ├── llm/                     # LLM service, routing, doc generation
│   │   ├── ingestion/               # Extraction orchestrator, queue service
│   │   ├── ops/                     # Queue registry, scheduling, heartbeat
│   │   ├── shared/                  # Assets, runs, events, config, database, forecast shared services
│   │   ├── tasks/                   # Celery tasks (modular)
│   │   │   ├── extraction.py        # Document processing
│   │   │   ├── sam.py               # SAM.gov sync
│   │   │   ├── salesforce.py        # Salesforce import
│   │   │   ├── sharepoint.py        # SharePoint sync
│   │   │   ├── scrape.py            # Web crawling
│   │   │   ├── procedures.py        # Procedure/pipeline execution
│   │   │   ├── forecasts.py         # Forecast sync
│   │   │   └── maintenance.py       # Email, cleanup, scheduled tasks
│   │   └── commands/                # CLI commands (seed, migrations, cleanup)
│   │
│   ├── connectors/                  # External data integrations
│   │   ├── adapters/                # Service adapter base + implementations
│   │   │   ├── base.py              # ServiceAdapter ABC — 3-tier config resolution
│   │   │   ├── playwright_adapter.py # Playwright rendering service adapter
│   │   │   ├── llm_adapter.py       # LLM (OpenAI-compatible) service adapter
│   │   │   └── document_service_adapter.py # Document extraction service adapter
│   │   ├── sam_gov/                 # SAM.gov API integration
│   │   ├── gsa_gateway/             # GSA Acquisition Gateway forecasts
│   │   ├── dhs_apfs/                # DHS APFS forecasts
│   │   ├── state_forecast/          # State Department forecasts
│   │   ├── salesforce/              # Salesforce CRM operations
│   │   ├── sharepoint/              # SharePoint sync
│   │   └── scrape/                  # Web scraping + Playwright
│   │
│   ├── cwr/                         # Curatore Workflow Runtime
│   │   ├── tools/                   # Function library (base, registry, content)
│   │   │   ├── primitives/          # Primitive functions (llm, search, output, notify, flow)
│   │   │   └── compounds/           # Compound multi-step functions
│   │   ├── contracts/               # Tool contracts (JSON Schema) and validation
│   │   ├── procedures/              # Procedure executor, loader, compiler
│   │   │   ├── compiler/            # AI procedure generator
│   │   │   ├── runtime/             # Procedure executor
│   │   │   └── store/               # Definitions, loader, discovery
│   │   ├── pipelines/               # Pipeline executor, loader, discovery
│   │   │   ├── runtime/             # Pipeline executor and definitions
│   │   │   └── store/               # Loader, discovery
│   │   ├── governance/              # Capability profiles and side-effect policies
│   │   └── observability/           # Run queries, traces, and metrics
│   │
│   └── templates/                   # Email templates
│
├── alembic/                         # Database migrations

frontend/
├── app/                             # Next.js App Router pages
│   ├── admin/                       # Functions, procedures, pipelines, queue, metadata
│   │   └── metadata/                # Metadata governance UI
│   ├── settings-admin/              # Admin settings (org, infra, users, metrics)
│   ├── sam/                         # SAM.gov interface
│   ├── salesforce/                  # Salesforce CRM (accounts, contacts, opportunities)
│   ├── forecasts/                   # Acquisition forecasts
│   ├── sharepoint-sync/             # SharePoint sync
│   └── scrape/                      # Web scraping
├── components/                      # React components
│   ├── procedures/                  # Procedure editor components
│   │   └── AIGeneratorPanel.tsx     # AI procedure generator panel
│   └── admin/                       # Admin dashboard components
└── lib/
    ├── api.ts                       # API client (all namespaces + contractsApi)
    ├── unified-jobs-context.tsx      # WebSocket-based job tracking
    └── job-type-config.ts            # Job type configuration

playwright-service/                  # Browser rendering microservice

mcp/                                 # MCP Gateway (AI tool server)
├── app/
│   ├── main.py                      # FastAPI app (HTTP transport)
│   ├── handlers/                    # MCP protocol handlers
│   ├── services/                    # Policy, backend client, converters
│   └── models/                      # MCP, OpenAI, policy models
├── stdio_server.py                  # STDIO server for Claude Desktop
├── Dockerfile                       # HTTP server image
├── Dockerfile.stdio                 # STDIO server image (Claude Desktop)
├── policy.yaml                      # Tool allowlist, clamps, side-effect policy
└── README.md                        # Full MCP Gateway documentation
```

---

## Key Data Models

| Model | Purpose |
|-------|---------|
| `Asset` | Document with provenance, version history, and pipeline status |
| `AssetVersion` | Individual versions of an asset |
| `ExtractionResult` | Extracted markdown with triage metadata |
| `Run` | Universal execution tracking with `trace_id` and `parent_run_id` for lineage |
| `RunGroup` | Parent-child job tracking for group completion |
| `RunLogEvent` | Structured logging for runs |
| `ContentItem` | Universal content wrapper for functions/procedures (in-memory) |

### Integration Models
| Model | Purpose |
|-------|---------|
| `SamSearch` | SAM.gov saved search configuration |
| `SamSolicitation` | Groups SAM.gov notices with same solicitation number |
| `SamNotice` | Individual SAM.gov notice |
| `ForecastSync` | Forecast sync configuration |
| `SharePointSyncConfig` | SharePoint folder sync configuration |
| `ScrapeCollection` | Web scraping project with seed URLs |
| `SalesforceConnection` | Salesforce org connection credentials |
| `SearchCollection` | Named search collection (static/dynamic/source_bound) |
| `CollectionChunk` | Isolated chunk in a collection's vector store (pgvector-backed) |
| `CollectionVectorSync` | Collection-to-external vector store sync target |

### Metadata Governance Models
| Model | Purpose |
|-------|---------|
| `AssetMetadata` | LLM-generated metadata (simple upsert, `is_canonical=True` default) |
| `MetadataFieldDefinition` | Registry of metadata fields per namespace (global + org-level) |
| `FacetDefinition` | Cross-domain facet definitions with operators |
| `FacetMapping` | Maps facets to JSON paths per content type |

### Workflow Models
| Model | Purpose |
|-------|---------|
| `Procedure` | Reusable workflow definitions (scheduled, event-driven) with version history |
| `ProcedureVersion` | Individual versioned snapshots of procedure definitions |
| `Pipeline` | Multi-stage document processing workflows |
| `ScheduledTask` | Database-backed scheduled maintenance |

---

## Core Services

Services are organized into domain-specific subdirectories under `backend/app/core/`.

### Auth (`core/auth/`)
| Service | Purpose |
|---------|---------|
| `auth_service.py` | JWT/API key authentication |
| `connection_service.py` | External connection management |
| `email_service.py` | Email sending (SMTP/SendGrid/SES) |
| `password_reset_service.py` | Password reset workflow |
| `verification_service.py` | Email verification |

### Ingestion (`core/ingestion/`)
| Service | Purpose |
|---------|---------|
| `extraction_orchestrator.py` | Extraction coordination via Document Service |
| `extraction_queue_service.py` | Extraction queue throttling and management |
| `extraction_result_service.py` | Result processing and storage |
| `bulk_upload_service.py` | Batch file uploads |
| `upload_integration_service.py` | Upload workflow integration |

### Search (`core/search/`)
| Service | Purpose |
|---------|---------|
| `pg_search_service.py` | Hybrid full-text + semantic search with facet filtering |
| `pg_index_service.py` | Document chunking, embedding, and indexing |
| `metadata_builders.py` | Metadata builder registry (asset pass-through + entity builders) |
| `chunking_service.py` | Document chunking logic |
| `document_chunker.py` | Chunk creation and formatting |
| `embedding_service.py` | Vector embedding generation |
| `collection_service.py` | Search collection CRUD and vector sync management |
| `collection_population_service.py` | Collection population orchestration (index copy, fresh chunk+embed) |
| `collection_stores/` | Store adapter pattern: `CollectionStoreAdapter` ABC, `PgVectorCollectionStore` |

### LLM (`core/llm/`)
| Service | Purpose |
|---------|---------|
| `llm_service.py` | LLM operations (delegates connection to `connectors/adapters/llm_adapter.py`) |
| `llm_routing_service.py` | Model selection with complexity estimation |
| `document_generation_service.py` | Document generation (PDF, DOCX, CSV) |

### Ops (`core/ops/`)
| Service | Purpose |
|---------|---------|
| `queue_registry.py` | Queue type definitions and capabilities |
| `priority_queue_service.py` | Priority-based job scheduling |
| `scheduled_task_service.py` | Database-backed scheduled tasks |
| `job_cancellation_service.py` | Job cancellation and cleanup |
| `maintenance_handlers.py` | System maintenance operations |
| `heartbeat_service.py` | Service health monitoring |
| `websocket_manager.py` | WebSocket connection management |

### Shared (`core/shared/`) + Storage (`core/storage/`)
| Service | Purpose |
|---------|---------|
| `asset_service.py` | Asset CRUD and version management |
| `asset_metadata_service.py` | LLM-generated metadata management |
| `artifact_service.py` | Artifact creation and retrieval |
| `run_service.py` | Run execution tracking |
| `run_group_service.py` | Parent-child job tracking for group completion |
| `run_log_service.py` | Structured run logging |
| `event_service.py` | Event emission for triggering procedures/pipelines |
| `document_service.py` | Document content handling |
| `storage_service.py` | Object storage operations |
| `minio_service.py` | MinIO/S3 client operations |
| `database_service.py` | Database operations |
| `config_loader.py` | Configuration management |
| `storage_path_service.py` | Object storage path utilities |
| `lock_service.py` | Distributed locking |
| `pubsub_service.py` | Pub/sub messaging |
| `status_mapper.py` | Run status mapping |
| `forecast_service.py` | Unified forecast access via VIEW |
| `forecast_sync_service.py` | Forecast sync configuration CRUD |

### CWR (`cwr/`)

CWR code is consolidated under `backend/app/cwr/`. See the project structure above.

| Subpackage | Purpose |
|------------|---------|
| `tools/` | Function library: base classes, registry, content service, primitives, compounds |
| `contracts/` | Tool contracts (JSON Schema) and procedure validation |
| `procedures/compiler/` | AI-powered procedure generation with contract constraints |
| `procedures/runtime/` | Procedure executor |
| `procedures/store/` | Procedure definitions, loader, discovery |
| `pipelines/runtime/` | Pipeline executor and definitions |
| `pipelines/store/` | Pipeline loader, discovery |
| `governance/` | Capability profiles, side-effect approval policies |
| `observability/` | CWR-specific run queries, trace reconstruction, metrics |

### Connectors (`connectors/`)
| Subdirectory | Service | Purpose |
|-------------|---------|---------|
| `adapters/` | `base.py` | ServiceAdapter ABC — 3-tier config resolution |
| `adapters/` | `playwright_adapter.py` | Playwright rendering service adapter |
| `adapters/` | `llm_adapter.py` | LLM (OpenAI-compatible) service adapter |
| `adapters/` | `document_service_adapter.py` | Document extraction service adapter |
| `sam_gov/` | `sam_service.py` | SAM.gov API integration |
| `sam_gov/` | `sam_pull_service.py` | SAM.gov data pull orchestration |
| `sam_gov/` | `sam_summarization_service.py` | SAM notice AI summarization |
| `sam_gov/` | `sam_api_usage_service.py` | SAM.gov API rate tracking |
| `gsa_gateway/` | `ag_forecast_service.py` | GSA Acquisition Gateway forecast CRUD |
| `gsa_gateway/` | `ag_pull_service.py` | GSA Acquisition Gateway API pull |
| `dhs_apfs/` | `apfs_forecast_service.py` | DHS APFS forecast CRUD |
| `dhs_apfs/` | `apfs_pull_service.py` | DHS APFS API pull |
| `state_forecast/` | `state_forecast_service.py` | State Dept forecast CRUD |
| `state_forecast/` | `state_pull_service.py` | State Dept scraping + Excel parsing |
| `salesforce/` | `salesforce_service.py` | Salesforce CRM operations |
| `salesforce/` | `salesforce_import_service.py` | Salesforce data import |
| `sharepoint/` | `sharepoint_service.py` | SharePoint operations |
| `sharepoint/` | `sharepoint_sync_service.py` | SharePoint folder sync |
| `scrape/` | `scrape_service.py` | Web scraping management |
| `scrape/` | `crawl_service.py` | Web crawling logic |
| `scrape/` | `playwright_client.py` | Browser rendering client |

### Metadata (`core/metadata/`)
| Service | Purpose |
|---------|---------|
| `registry_service.py` | Metadata field/facet governance (YAML baseline + DB overrides, 5-min cache) |
| `registry/namespaces.yaml` | Baseline namespace definitions |
| `registry/fields.yaml` | Baseline field definitions |
| `registry/facets.yaml` | Baseline facet definitions and mappings |

---

## Tool Contracts & Governance

Functions expose formal **tool contracts** — JSON Schema-based definitions with governance metadata. The contracts system enables the AI procedure generator to understand function capabilities and constraints.

### Contract Fields
| Field | Purpose |
|-------|---------|
| `input_schema` | JSON Schema for function parameters |
| `output_schema` | JSON Schema for function return values |
| `side_effects` | Whether function modifies external state (email, metadata, artifacts) |
| `is_primitive` | `true` = single operation, `false` = compound (orchestrates sub-steps) |
| `payload_profile` | `"thin"` (IDs/titles/scores), `"full"` (complete data), `"summary"` (condensed) |
| `exposure_profile` | Access policy: `{"procedure": true, "agent": true}` |
| `requires_llm` | Whether function needs an LLM connection |
| `tags` | Categorization tags for filtering |

### Key Files
- `backend/app/cwr/tools/schema_utils.py` — `ContractView` frozen dataclass (replaces deleted `ToolContract`)
- `backend/app/cwr/tools/base.py` — `FunctionMeta` with `input_schema`/`output_schema` as JSON Schema dicts; `to_contract_dict()` and `as_contract()` methods
- `backend/app/cwr/contracts/validation.py` — Procedure validation with facet checking
- `backend/app/api/v1/cwr/routers/contracts.py` — REST API endpoints
- `backend/app/api/v1/cwr/schemas.py` — `FunctionSchema` includes governance fields; `ToolContractResponse` for contract API
- `backend/app/cwr/procedures/compiler/ai_generator.py` — System prompt includes CONTRACT & GOVERNANCE CONSTRAINTS section
- `frontend/lib/api.ts` — `contractsApi` client + `ToolContract` TypeScript interface; `FunctionMeta` with `input_schema`/`output_schema`

### Governance in the Procedure Generator
The AI generator's system prompt includes contract constraint rules:
1. Functions with `side_effects=true` are placed late in workflows after data gathering
2. `payload_profile="thin"` search functions require a `get_content` step before LLM functions
3. External-exposure functions (email, webhook) are guarded with conditionals
4. `requires_llm=true` functions fail without an LLM connection

### Frontend: Function Catalog
The procedure editor (`/admin/procedures/new`) displays governance metadata:
- **Badges**: Side effects (red/green), LLM Required (purple), Payload profile (blue/green/amber), Compound (gray)
- **Tags**: As small pills on each function
- **Output Schema**: Structured type, fields, and variants when expanded
- **Examples**: Collapsible YAML snippets

---

## Key Routers (namespaced under `backend/app/api/v1/`)

**Admin** (`admin/routers/`):
| Router | Endpoints |
|--------|-----------|
| `system.py` | Health checks (individual + comprehensive), extraction engines |
| `auth.py` | Login, register, password reset |
| `users.py` | User CRUD, roles |
| `organizations.py` | Organization settings |
| `connections.py` | External connection management |
| `api_keys.py` | API key management |
| `scheduled_tasks.py` | Scheduled maintenance task management |

**Data** (`data/routers/`):
| Router | Endpoints |
|--------|-----------|
| `assets.py` | Asset CRUD, versions, content, download, bulk download, delete |
| `storage.py` | Object storage: artifacts, browsing, upload proxy |
| `search.py` | Full-text + semantic search |
| `collections.py` | Search collections CRUD, vector sync targets |
| `metadata.py` | Metadata governance: catalog, namespaces, fields, facets |
| `sam.py` | SAM.gov searches, solicitations, notices |
| `salesforce.py` | Salesforce accounts, contacts, opportunities |
| `forecasts.py` | Forecast syncs and unified view |
| `sharepoint_sync.py` | SharePoint sync configuration |
| `scrape.py` | Web scraping collections |
| `render.py` | Document rendering |
| `webhooks.py` | Webhook integrations |

**Ops** (`ops/routers/`):
| Router | Endpoints |
|--------|-----------|
| `runs.py` | Run status, logs, retry |
| `queue_admin.py` | Job Manager: registry, active jobs, cancel |
| `metrics.py` | Procedure execution metrics |
| `websocket.py` | Real-time job status updates |

**CWR** (`cwr/routers/`):
| Router | Endpoints |
|--------|-----------|
| `functions.py` | Function browser and execution (includes governance fields) |
| `procedures.py` | Procedure CRUD, execution, triggers, versions |
| `pipelines.py` | Pipeline CRUD and execution |
| `contracts.py` | Tool contract schemas (input/output JSON Schema + governance) |

---

## Queue Architecture

All background jobs are managed through the Queue Registry system. See [Queue System](docs/QUEUE_SYSTEM.md) for details.

**Queue Types:**
| Queue | Run Type | Purpose |
|-------|----------|---------|
| Extraction | `extraction` | Document processing |
| SAM.gov | `sam_pull` | SAM.gov data sync |
| Forecasts | `forecast_pull` | Acquisition forecast sync |
| Web Scrape | `scrape` | Web crawling |
| SharePoint | `sharepoint_sync` | SharePoint sync |
| Maintenance | `system_maintenance` | Background tasks |
| Procedure | `procedure` | Workflow execution |
| Pipeline | `pipeline` | Pipeline execution |

---

## Search Architecture

PostgreSQL with pgvector for hybrid full-text + semantic search:

- **Database**: By default shares the primary PostgreSQL instance. Optional `search.database_url` in config.yml allows pointing search at a dedicated pgvector instance for workload isolation (Phase 1: config-level; Phase 2: runtime separation).
- **Full-text search**: PostgreSQL tsvector + GIN indexes
- **Semantic search**: pgvector embeddings (1536-dim via OpenAI)
- **Hybrid mode**: Configurable keyword/semantic weighting
- **Chunking**: ~1500 char chunks with 200 char overlap
- **Namespaced metadata**: `search_chunks.metadata` uses nested JSONB namespaces (`source`, `sharepoint`, `sam`, `salesforce`, `forecast`, `custom`) built via `MetadataBuilder` registry. Connectors write namespaced `Asset.source_metadata` directly; asset builders pass it through to search chunks.
- **Metadata registry**: DB-backed field and facet definitions in `metadata_field_definitions`, `facet_definitions`, `facet_mappings` tables. Global baseline loaded from YAML (`backend/app/core/metadata/registry/`), org-level overrides in DB. Managed by `MetadataRegistryService`.
- **Facet-based filtering**: `facet_filters` parameter on search resolves cross-domain facets (e.g., `{"agency": "GSA"}` maps to `sam.agency` for SAM data and `forecast.agency_name` for forecasts). Preferred over raw `metadata_filters`.
- **Raw metadata filtering**: `metadata_filters` parameter still available for JSONB `@>` containment queries on the GIN index
- **AssetMetadata bridge**: Canonical LLM-generated metadata (simple upsert, `is_canonical=True` default) propagated to `custom` namespace for searchability
- **Schema discovery**: `GET /api/v1/data/search/metadata-schema` returns namespaces, fields, sample values, doc counts from registry service (cached 5 min)
- **Governance APIs**: `GET /api/v1/data/metadata/catalog` returns full catalog; additional endpoints for namespaces, fields, field stats, and facets

Indexed content types: assets, SAM solicitations/notices, forecasts, scraped pages.

**Search Collections** (isolated vector stores):
- `SearchCollection` model: Named groups of indexed content (static, dynamic, source_bound)
- `collection_chunks` table: Isolated per-collection vector store with own embeddings, tsvector, and flat metadata
- `CollectionStoreAdapter` pattern: Pluggable backends — `PgVectorCollectionStore` (local, default) or external adapters (future)
- `CollectionPopulationService`: Populate from core index (fast, reuses embeddings) or fresh re-chunk + embed (async Celery)
- `CollectionVectorSync` links collections to external vector stores (Pinecone, OpenSearch, etc.) via the Connection pattern
- `vector_store` connection type registered in `ConnectionTypeRegistry`
- CWR functions: `search_collection` (collection-scoped search via store adapter); discoverable via `discover_data_sources(source_type="search_collection")`
- Optional `search.database_url` in config.yml for dedicated pgvector workload isolation

---

## Data Flow

```
Upload → Asset Created → Extraction (via Document Service) → Indexing → Search Ready
                                    ↓
                             Run (tracks execution)
                                    ↓
                             RunLogEvent (logs)
```

1. **Upload**: `POST /api/v1/data/storage/upload/proxy` creates Asset
2. **Extraction**: Backend POSTs file to Document Service, which handles triage + engine selection internally (fast_pdf, markitdown, or docling)
3. **Indexing**: Chunks content, generates embeddings, indexes to search
4. **Access**: `GET /api/v1/data/assets/{id}` returns asset with extraction

### Run Tracing

Runs support distributed tracing for multi-step workflows:
- `trace_id` — Groups all related runs under a single trace (e.g., a procedure and its child steps)
- `parent_run_id` — Direct parent-child relationship between runs

---

## Object Storage Structure

```
curatore-uploads/{org_id}/
├── uploads/{asset_uuid}/{filename}      # File uploads
├── scrape/{collection}/pages/           # Scraped web pages
├── sharepoint/{site}/{path}/            # SharePoint files
└── sam/{agency}/{bureau}/               # SAM.gov attachments

curatore-processed/{org_id}/             # Extracted markdown
curatore-temp/{org_id}/                  # Temporary files
```

---

## Adding Features

### New API Endpoint
1. Create router in the appropriate namespace (`admin/`, `data/`, `ops/`, or `cwr/`)
2. Add Pydantic models to the namespace's `schemas.py`
3. Implement service in the appropriate `backend/app/core/` subdirectory
4. Register router in the namespace's `__init__.py`
5. Update `frontend/lib/api.ts` (add TypeScript interfaces + API methods)

### New Service
1. Identify the correct location:
   - **CWR code** (functions, procedures, pipelines, contracts, governance) → `backend/app/cwr/`
   - **Connectors** (external data integrations) → `backend/app/connectors/`
   - **Other services** → `backend/app/core/` subdirectory:
     - `auth/` — Authentication, authorization, identity
     - `ingestion/` — Document upload, extraction orchestration
     - `llm/` — LLM calls, routing, document generation
     - `ops/` — Queue management, scheduling, monitoring
     - `search/` — Search, indexing, embeddings, chunking
     - `shared/` — Cross-cutting (assets, runs, events, storage, config)
2. Create the service module in that subdirectory
3. Export from the subdirectory's `__init__.py` if needed

### New Celery Task
1. Add task to the appropriate module in `backend/app/core/tasks/`:
   - `extraction.py` — Document processing tasks
   - `sam.py` — SAM.gov tasks
   - `salesforce.py` — Salesforce tasks
   - `sharepoint.py` — SharePoint tasks
   - `scrape.py` — Web scraping tasks
   - `procedures.py` — Procedure/pipeline execution
   - `forecasts.py` — Forecast tasks
   - `maintenance.py` — Maintenance/scheduled tasks
2. Use `@celery_app.task(name="app.tasks.module.my_task")`
3. Re-export from `backend/app/core/tasks/__init__.py` for backward compatibility
4. Create Run record for tracking

### New Function
1. Create function module in `backend/app/cwr/tools/primitives/<category>/` (or `compounds/` for multi-step functions)
2. Define `FunctionMeta` with governance fields (`side_effects`, `payload_profile`, `exposure_profile`, etc.)
3. Register in `backend/app/cwr/tools/registry.py`
4. Contract is auto-derived via `FunctionMeta.as_contract()` — define `input_schema` and `output_schema` as JSON Schema dicts directly on `FunctionMeta`

### New Queue Type
See [Queue System - Adding New Queue Types](docs/QUEUE_SYSTEM.md#adding-new-queue-types)

### New Data Integration
See [Data Connections Guide](docs/DATA_CONNECTIONS.md)

---

## Frontend Patterns

### Design System
- **Colors**: Indigo/purple primary, emerald success, red error, amber warning
- **Icons**: Lucide React (`lucide-react`)
- **Dark Mode**: All components use `dark:` prefix

### Real-Time Job Tracking
WebSocket-based with automatic polling fallback:

```tsx
import { useActiveJobs } from '@/lib/context-shims'

function MyPage() {
  const { addJob, getJobsForResource, isResourceBusy } = useActiveJobs()

  const handleStart = async () => {
    const result = await api.startJob(resourceId)
    addJob({
      runId: result.run_id,
      jobType: 'sharepoint_sync',
      displayName: 'My Sync',
      resourceId: resourceId,
      resourceType: 'sharepoint_config',
    })
  }
}
```

**Key Files:**
- `frontend/lib/unified-jobs-context.tsx` - Job tracking
- `frontend/lib/context-shims.ts` - Backward-compatible hooks
- `frontend/components/ui/RunningJobBanner.tsx` - Job status banner

### API Client (`frontend/lib/api.ts`)

The API client is organized into namespace-specific exports:

| Export | Namespace | Key Methods |
|--------|-----------|-------------|
| `systemApi` | Admin | `getHealth`, `getLLMStatus`, `getExtractionEngines` |
| `authApi` | Admin | `login`, `register`, `resetPassword` |
| `usersApi` | Admin | `listUsers`, `updateUser` |
| `assetsApi` | Data | `listAssets`, `getAsset`, `deleteAsset` |
| `searchApi` | Data | `search`, `getMetadataSchema` |
| `collectionsApi` | Data | `listCollections`, `getCollection`, `createCollection`, `deleteCollection`, `listVectorSyncs`, `addVectorSync` |
| `metadataApi` | Data | `getCatalog`, `getNamespaces`, `getFacets` |
| `samApi` | Data | `getSearches`, `getSolicitations`, `getNotices` |
| `salesforceApi` | Data | `getAccounts`, `getContacts`, `getOpportunities` |
| `forecastsApi` | Data | `getSyncs`, `getForecasts` |
| `sharepointSyncApi` | Data | `getConfigs`, `createConfig` |
| `scrapeApi` | Data | `getCollections` |
| `objectStorageApi` | Data | `browse`, `upload`, `download` |
| `runsApi` | Ops | `listRuns`, `getRunLogs` |
| `metricsApi` | Ops | `getProcedureMetrics` |
| `functionsApi` | CWR | `listFunctions`, `executeFunction` |
| `contractsApi` | CWR | `listContracts`, `getContract`, `getInputSchema`, `getOutputSchema` |
| `proceduresApi` | CWR | `listProcedures`, `createProcedure`, `runProcedure`, `generateProcedure` |
| `pipelinesApi` | CWR | `listPipelines`, `runPipeline` |

---

## API Quick Reference

```
Admin:
  Health:      GET /api/v1/admin/system/health/comprehensive
  Auth:        POST /api/v1/admin/auth/login, /register
  Users:       GET /api/v1/admin/users, PUT /users/{id}

Data:
  Assets:      GET/POST /api/v1/data/assets, DELETE /assets/{id}
  Content:     GET /api/v1/data/assets/{id}/content, /download
  Storage:     POST /api/v1/data/storage/upload/proxy
  Search:      POST /api/v1/data/search, GET /search/metadata-schema
  Collections: GET/POST /api/v1/data/collections, GET/PUT/DELETE /collections/{id}
  Coll Ops:    POST /collections/{id}/populate, /populate/fresh, /clear, DELETE /collections/{id}/assets
  Metadata:    GET /api/v1/data/metadata/catalog, /namespaces, /facets
  SAM.gov:     GET /api/v1/data/sam/searches, /solicitations, /notices
  Salesforce:  GET /api/v1/data/salesforce/accounts, /contacts
  Forecasts:   GET /api/v1/data/forecasts/syncs, GET /forecasts

Ops:
  Runs:        GET /api/v1/ops/runs, GET /runs/{id}/logs
  Queue:       GET /api/v1/ops/queue/jobs, POST /queue/jobs/{id}/cancel
  Metrics:     GET /api/v1/ops/metrics/procedures

CWR:
  Functions:   GET /api/v1/cwr/functions, POST /functions/{name}/execute
  Contracts:   GET /api/v1/cwr/contracts, GET /contracts/{name}
  Contracts:   GET /api/v1/cwr/contracts/{name}/input-schema, /output-schema
  Procedures:  GET /api/v1/cwr/procedures, POST /procedures/{slug}/run
  Procedures:  POST /api/v1/cwr/procedures/generate (AI generation)
  Pipelines:   GET /api/v1/cwr/pipelines, POST /pipelines/{slug}/run
```

---

## Debugging

```bash
# Check services
docker ps

# View logs
docker-compose logs -f backend
docker-compose logs -f worker

# Check Celery tasks
docker exec -it curatore-worker celery -A app.celery_app inspect active

# Check Redis
docker exec -it curatore-redis redis-cli keys '*'

# Check PostgreSQL
docker exec -it curatore-postgres psql -U curatore -d curatore -c "\dt"
```

---

## Related Documentation

| Document | Description |
|----------|-------------|
| [MCP Gateway](mcp/README.md) | AI tool server for Claude Desktop, Open WebUI, and MCP clients |
| [MCP & Open WebUI](docs/MCP_OPEN_WEBUI.md) | Open WebUI integration guide |
| [Search & Indexing](docs/SEARCH_INDEXING.md) | Hybrid search, pgvector, chunking, embeddings, reindexing |
| [Metadata Catalog](docs/METADATA_CATALOG.md) | Namespaces, fields, facets, reference data, registry service |
| [Queue System](docs/QUEUE_SYSTEM.md) | Queue architecture, job groups, cancellation |
| [SAM.gov Integration](docs/SAM_INTEGRATION.md) | SAM.gov data model and API |
| [Salesforce Integration](docs/SALESFORCE_INTEGRATION.md) | Salesforce CRM integration |
| [SharePoint Integration](docs/SHAREPOINT_INTEGRATION.md) | SharePoint folder sync |
| [Forecast Integration](docs/FORECAST_INTEGRATION.md) | Acquisition forecast sources |
| [Functions & Procedures](docs/FUNCTIONS_PROCEDURES.md) | Workflow automation |
| [Data Connections](docs/DATA_CONNECTIONS.md) | Adding new integrations |
| [Document Processing](docs/DOCUMENT_PROCESSING.md) | Extraction pipeline |
| [Maintenance Tasks](docs/MAINTENANCE_TASKS.md) | Scheduled background tasks |
| [Configuration](docs/CONFIGURATION.md) | Environment and YAML config |
| [API Documentation](docs/API_DOCUMENTATION.md) | Complete API reference |
