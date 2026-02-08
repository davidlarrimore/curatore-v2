# Curatore Platform Architecture Evolution
## Data Core & Curatore Workflow Runtime (CWR)
### Contract-Driven Automation, Deterministic Execution, and AI-Compiled Workflows

---

# Executive Summary

Curatore has evolved into a full data automation platform that includes:

- Enterprise data connectors (SAM.gov, SharePoint, web scraping via Playwright)
- Ingestion and extraction pipelines
- Metadata enrichment and indexing
- Redis + Celery distributed job orchestration
- Administrative management APIs
- Search and catalog APIs
- Deterministic workflow automation (procedures and pipelines)
- AI-assisted procedure compilation

As capabilities have expanded, architectural boundaries between ingestion, metadata, automation, and AI have blurred.

This document defines a structural refactor of Curatore into clearly defined bounded contexts:

1. **Curatore Data Core** — governs how data enters, is structured, enriched, indexed, and queried.
2. **Curatore Workflow Runtime (CWR)** — governs how deterministic automation executes on top of that data using contract-driven tools.

This whitepaper is written as an implementation guide for building and refactoring the platform. It includes:

- Target module structure
- Deployment model
- Worker separation strategy
- Tool contract requirements
- Procedure compilation architecture
- Facet and metadata evolution
- Execution runtime design

The system remains a modular monolith, but deploys multiple worker containers for isolation and scalability.

---

# 1. Platform Context and Refactor Rationale

Curatore is not simply:

- A backend API
- A workflow engine
- A connector framework
- An LLM integration layer

It is a platform that performs:

- Data ingestion
- Metadata modeling
- Search and retrieval
- Analytics workflows
- Automated reporting
- AI-assisted business automation

Historically, components such as `functions`, `procedures`, `pipelines`, and job orchestration grew organically.

This has led to:

- Blurred ownership boundaries
- Confusion between Python functions and workflow “functions”
- Unclear separation between data concerns and automation concerns
- Difficulty reasoning about agent compatibility vs deterministic runtime

The refactor formalizes separation into:

## Curatore Data Core (data plane)
## Curatore Workflow Runtime (execution plane)

The job layer (Celery/Redis) remains shared infrastructure across both.

---

# 2. High-Level Architecture

```

Curatore Platform
│
├── Curatore Data Core
│     ├── Connectors
│     ├── Ingestion & Extraction
│     ├── ContentItem Abstraction
│     ├── Metadata Registry
│     ├── Facets
│     ├── Search (vector + hybrid + filters)
│     └── Data Catalog
│
├── Curatore Workflow Runtime (CWR)
│     ├── Tool Contracts
│     ├── Primitive Tools
│     ├── Compound Tools
│     ├── Deterministic Procedures
│     ├── Pipelines (stateful)
│     ├── Runtime Executor
│     ├── AI Procedure Compiler
│     └── Governance & Observability
│
└── Job Infrastructure
├── Redis
├── Celery
├── Worker Pools
└── Scheduler

```

---

# 3. Deployment Model

Curatore remains a **single codebase**, deployed as multiple containers.

## Containers

| Container | Role |
|------------|------|
| curatore-api | FastAPI control plane |
| curatore-worker-connectors | SAM / SharePoint / scraping jobs |
| curatore-worker-extract | Extraction and parsing |
| curatore-worker-index | Indexing and embedding |
| curatore-worker-cwr | Procedure & pipeline execution |

Each worker subscribes to specific Celery queues.

---

# 4. Curatore Data Core

## Responsibilities

Data Core owns:

- Asset models
- ContentItem abstraction
- Metadata storage (JSONB + structured fields)
- Metadata schema registry
- Facet registry and mappings
- Search services
- Connector implementations
- Extraction pipelines
- Indexing

CWR must depend on Data Core through explicit service interfaces.

---

## 4.1 Backend Structure (Data Core)

```

backend/app/
core/
content/
content_item.py
content_service.py
metadata/
schema_registry.py
metadata_store.py
enrichment.py
facets/
registry.py
mappings.py
validation.py
search/
search_service.py
hybrid_search.py
metadata_filters.py
catalog/
discovery.py
data_dictionary.py

connectors/
sam_gov/
sharepoint/
scraping_playwright/

ingestion/
extraction/
normalization/
indexing/

````

---

## 4.2 Metadata Schema Registry

A first-class schema system describing:

- Namespaces
- Field types
- Indexability
- Cardinality
- Facet eligibility

Example:

```python
MetadataNamespace(
    name="sam",
    fields=[
        Field(name="agency", type="string", index=True, facet=True),
        Field(name="naics_code", type="string", index=True, facet=True),
    ]
)
````

Used for:

* Validation
* Search introspection
* Tool contract generation
* AI procedure generator context

---

## 4.3 Facet System

Facets provide cross-domain filtering.

Example:

```
Facet: agency
  asset → metadata.sam.agency
  solicitation → fields.agency
  notice → fields.agency
```

Search APIs and CWR tools should prefer `facet_filters` over raw metadata filters.

---

## 4.4 Payload Discipline

Search returns thin results by default:

* id
* title
* score
* snippet
* metadata summary

Full text requires explicit materialization:

```yaml
- function: materialize_text
  params:
    ids: "{{ steps.search_results[*].id }}"
    max_chars_per_item: 8000
```

This ensures cost control and scalability.

---

# 5. Curatore Workflow Runtime (CWR)

CWR is the deterministic execution layer.

It is not an autonomous agent system.

Agentic behavior exists only at compile-time via the AI Procedure Generator.

---

## 5.1 Responsibilities

* Tool contracts (JSON Schema)
* Primitive tools
* Compound tools
* Procedure execution
* Pipeline execution
* AI Procedure Compiler
* Governance (side-effect approval)
* Run tracking
* Concurrency control

---

## 5.2 Backend Structure (CWR)

```
backend/app/
  cwr/
    contracts/
      tool_contracts.py
      procedure_schema.json
      validation.py

    tools/
      primitives/
      compounds/
      registry.py

    procedures/
      compiler/
        ai_generator.py
        optimizer.py
      runtime/
        executor.py
        step_runner.py
        templating.py
      store/
        definitions.py
        versioning.py

    pipelines/
      runtime/
      state.py

    governance/
      approvals.py
      capability_profiles.py

    observability/
      runs.py
      traces.py
      metrics.py
```

---

# 6. Tool Contracts

Each primitive tool must expose:

```python
ToolContract(
    name="search_assets",
    description="Search assets using hybrid search",
    input_schema={...},      # JSON Schema
    output_schema={...},     # JSON Schema
    payload_profile="thin",
    side_effects=False,
    exposure_profile={
        "procedure": True,
        "agent": "readonly"
    }
)
```

Contracts are canonical. YAML is compiled to JSON for runtime.

---

# 7. Deterministic Procedures

Procedures:

* Static
* Stored
* Versioned
* Deterministic
* Executed by CWR worker

No runtime planning occurs.

AI only generates or refines procedure definitions.

---

# 8. AI Procedure Compiler

The AI Procedure Generator is a compiler.

Responsibilities:

* Interpret user intent
* Select tools
* Prefer compound tools
* Insert materialization steps
* Apply facet filters
* Validate JSON schemas
* Optimize payload size
* Emit final procedure definition

Execution does not use LLM reasoning.

---

# 9. Pipelines

Pipelines extend procedures by:

* Tracking per-item state
* Supporting checkpoints
* Allowing resumability
* Managing large collections

Executed via CWR worker plane.

---

# 10. Celery Integration

Queues:

* connectors
* scrape
* extract
* index
* cwr

CWR execution is triggered by:

* API request
* Cron schedule
* Event emission

Runs are persisted and traceable.

---

# 11. API Namespacing

```
/api/v1/admin/*
/api/v1/data/*
/api/v1/ops/*
/api/v1/cwr/*
```

CWR endpoints:

* tools
* contracts
* procedures
* pipelines
* runs
* compiler/generate

---

# 12. Strategic Outcomes

This architecture provides:

* Clear ownership boundaries
* Isolated workload scaling
* Deterministic automation
* Agent-compatible contracts
* Metadata and facet evolution
* Compile-time AI planning
* Runtime safety
* Long-term extensibility

---

# Final Definition

Curatore evolves into:

A modular data platform with a dedicated Workflow Runtime capable of deterministic automation and AI-assisted compilation, built on contract-driven tooling and scalable job infrastructure.

---





ADDENDUM

# Addendum: Metadata Catalog, Facets, and Organization-Scoped Governance

## Purpose

This addendum defines how Curatore manages its metadata model, facet system, and organization-scoped schema evolution in a scalable and governable way.

Curatore supports:

- Dynamic metadata fields
- Cross-domain facets
- Organization-scoped data isolation
- AI-driven procedure compilation (CWR)
- Deterministic search and filtering

To support these capabilities, metadata must become a formally governed subsystem within **Curatore Data Core**, not an implicit JSONB convention.

This document defines:

1. The metadata catalog model  
2. The facet system  
3. Global vs organization-scoped schema layering  
4. Runtime registry resolution  
5. Required APIs  
6. Frontend requirements  

---

# 1. Architectural Positioning

Metadata governance belongs to **Curatore Data Core**, not CWR.

CWR consumes metadata definitions but does not define or mutate the metadata schema model.

```

Curatore Data Core
│
├── Metadata Schema Registry
├── Field Catalog
├── Facet Registry
└── Search & Indexing

```

The registry must be organization-aware even if only a single “Default” organization exists today.

All metadata and facet resolution must be scoped to `organization_id`.

---

# 2. Metadata Catalog Model

The Metadata Catalog consists of three linked registries:

1. Field Registry (Data Dictionary)  
2. Asset-Type Applicability Rules  
3. Facet Registry (Cross-Domain Filters)  

---

## 2.1 Field Registry (Data Dictionary)

Each metadata field must be formally registered.

### Required Attributes

- `namespace` (e.g., sam, custom, security)
- `field_name`
- `data_type` (string, number, boolean, date, enum, array, object)
- `indexed` (boolean)
- `facetable` (boolean)
- `applicable_asset_types`
- `description`
- `examples`
- `sensitivity_tag` (optional)
- `version`
- `organization_id` (nullable: null = global baseline)

### Example (Conceptual)

```

namespace: sam
field: agency
type: string
indexed: true
facetable: true
applies_to: [notice, solicitation]
organization_id: null

```

This registry is authoritative for:

- Search filter validation
- Facet eligibility
- Tool contract generation
- AI procedure generator context
- UI discovery

---

## 2.2 Asset-Type Applicability

Curatore supports multiple content types:

- asset
- solicitation
- notice
- scraped_asset
- forecast
- etc.

Each metadata field must explicitly declare which content types it applies to.

This prevents:

- Invalid cross-type filtering
- Incorrect AI-generated procedures
- Ambiguous query construction

---

## 2.3 Facet Registry (Cross-Domain Filters)

Facets are user-facing filter abstractions that map to underlying metadata paths.

They unify filtering across asset types.

### Example

Facet: `agency`

Mappings:

- notice → fields.agency
- solicitation → fields.agency
- asset → metadata.sam.agency

Facets are not metadata fields.
They are semantic abstractions layered on top of metadata paths.

Search tools and CWR tools should prefer `facet_filters` over raw `metadata_filters`.

---

# 3. Global vs Organization-Scoped Registry

Curatore must support layered metadata governance.

Even if only one “Default” organization exists today, the system must behave as multi-tenant-aware.

---

## 3.1 Baseline (Global) Registry

Global metadata definitions are:

- Version-controlled in files
- Reviewed via PR
- Considered product-level schema

Location:

```

backend/app/core/metadata/registry/
namespaces.yaml
fields.yaml
facets.yaml

```

These definitions have:

```

organization_id = null

```

---

## 3.2 Organization-Level Overrides

Organizations may define:

- Custom namespaces
- Custom fields
- Custom facet mappings
- Field indexing flags
- Facet enable/disable behavior

These are stored in the database with:

```

organization_id = <org_uuid>

```

---

## 3.3 Effective Registry Resolution

All metadata and facet resolution must be organization-aware.

At runtime:

```

effective_registry(org_id) =
merge(global_registry, org_registry[org_id])

```

Resolution order:

1. Load global baseline definitions
2. Apply organization-level overrides/extensions
3. Produce effective registry for that organization

All search validation, CWR contract generation, and UI discovery use the effective registry.

---

# 4. Registry Storage Model

Two supported approaches:

---

## Option A (Preferred Long-Term): Structured Tables

Tables:

- metadata_field_definitions
- facet_definitions
- facet_mappings

Columns include:

- organization_id (nullable)
- namespace
- field_name
- schema_json
- version
- status (active/deprecated)
- created_at
- created_by

This enables:

- Auditing
- Deprecation tracking
- Controlled evolution
- Usage analysis

---

## Option B (Simpler Initial Model): JSON Registry Per Organization

Add to Organization model:

```

organization.metadata_registry_json
organization.facet_registry_json

```

Files provide baseline.
Org JSON provides overrides.
Runtime compiles both.

This is simpler to implement but less queryable long-term.

---

# 5. Search and Indexing Implications

Metadata governance directly affects:

- Indexing
- Faceting
- Filtering
- Payload generation

## 5.1 Indexing Rules

If a field is marked `indexed = true`, indexing jobs must:

- Ensure the field is included in search filters
- Update search indexes
- Potentially trigger reindex/backfill jobs

Index updates must be organization-scoped.

---

## 5.2 Facet Materialization

Facet queries may:

- Map to multiple underlying metadata paths
- Require normalized value storage
- Require precomputed aggregations (optional optimization)

Facet mapping resolution must occur before search execution.

---

# 6. Required Metadata APIs

All endpoints must be organization-aware.

```

GET /api/v1/data/metadata/catalog
GET /api/v1/data/metadata/namespaces
GET /api/v1/data/metadata/fields/{field}
GET /api/v1/data/metadata/fields/{field}/stats
GET /api/v1/data/facets
GET /api/v1/data/facets/{facet}/mappings

```

Each request must resolve against:

```

effective_registry(current_org_id)

```

Optional but recommended:

```

GET /api/v1/data/metadata/fields/{field}/usage

```

---

# 7. Frontend Requirements

A metadata governance UI is required.

Even with a single organization today.

---

## Phase 1 (Required)

### Metadata Catalog Browser

- View namespaces
- View fields
- See types, indexing, facetable status
- See applicable asset types
- View top values (if indexed)

### Facet Manager

- View facet list
- View mappings per asset type
- Validate mapping behavior
- Show preview query resolution

If only one organization exists, org selector may be hidden but logic remains org-aware.

---

## Phase 2 (Optional / Advanced)

### Org-Level Field Editor (Admin Only)

- Add namespace
- Add field
- Configure indexing
- Configure facetable status
- Trigger reindex job

### Deprecation Manager

- Mark fields deprecated
- Track field versions
- Show migration warnings

---

# 8. Interaction with CWR and AI Procedure Compiler

CWR must never assume raw JSON metadata structure.

Instead:

- Tool contracts derive from effective metadata registry
- Procedure generator is provided effective metadata schema context
- LLM prompts include allowed fields and facets for the organization

This reduces hallucinated filters and invalid search references.

---

# 9. Strategic Outcomes

This organization-aware metadata governance model enables:

- Controlled schema evolution
- Safe dynamic metadata
- Cross-domain facet filtering
- AI-compatible schema discovery
- Deterministic search validation
- Multi-tenant readiness
- Long-term maintainability

Even with a single “Default” organization today, building the system as organization-aware prevents future architectural rewrites.

Metadata becomes a governed platform capability rather than an implicit convention.

---

End of Addendum