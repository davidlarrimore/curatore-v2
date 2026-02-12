# Metadata Catalog

The Metadata Catalog is Curatore's governance system for organizing, discovering, and filtering metadata across all content types. It defines what metadata fields exist, which are searchable/filterable, and how cross-domain facets map to different data sources.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Namespaces](#namespaces)
3. [Fields](#fields)
4. [Facets](#facets)
5. [Reference Data](#reference-data)
6. [Metadata Propagation Flow](#metadata-propagation-flow)
7. [Data Source Type Registry](#data-source-type-registry)
8. [MetadataRegistryService](#metadataregistryservice)
9. [API Endpoints](#api-endpoints)
10. [Admin UI](#admin-ui)
11. [MCP / AI Agent Discovery](#mcp--ai-agent-discovery)
12. [How-To Guides](#how-to-guides)
13. [Key Files](#key-files)

---

## Architecture Overview

```
                YAML Baseline (checked into repo)
                ─────────────────────────────────
                namespaces.yaml   fields.yaml
                facets.yaml       reference_data.yaml
                data_sources.yaml
                        │
                        ▼
              ┌─────────────────────────┐
              │ MetadataRegistryService  │ ◄── Singleton, loads YAML on first access
              │  (registry_service.py)   │     Seeds DB on startup (load_baseline)
              │                         │     5-min TTL cache per org
              └───────┬─────────────────┘
                      │
            ┌─────────┴──────────┐
            ▼                    ▼
   ┌─────────────────┐  ┌──────────────────┐
   │   DB Tables      │  │  In-Memory Cache  │
   │ (org overrides)  │  │  (global baseline │
   │                  │  │   + org merges)   │
   │ metadata_field_  │  └──────────────────┘
   │  definitions     │          │
   │ facet_definitions│          ▼
   │ facet_mappings   │  ┌──────────────────┐
   │ facet_reference_ │  │ Consumers:       │
   │  values/aliases  │  │  - Search API    │
   └──────────────────┘  │  - Metadata API  │
                         │  - MCP Gateway   │
                         │  - CWR Functions  │
                         │  - Admin UI      │
                         └──────────────────┘
```

The system uses a **YAML-first** approach:

1. **Global baseline** is defined in YAML files checked into the repo
2. On startup, YAML is synced to DB tables (`load_baseline`)
3. Organizations can add **org-level overrides** via the admin UI or API
4. The effective registry merges global + org overrides, cached for 5 minutes

---

## Namespaces

Namespaces organize metadata fields into logical groups by data source. They define the top-level keys in `search_chunks.metadata` JSONB column.

**File**: `backend/app/core/metadata/registry/namespaces.yaml`

| Namespace | Display Name | Description |
|-----------|-------------|-------------|
| `source` | Source Info | Common fields for all assets (storage path, upload info) |
| `sharepoint` | SharePoint | SharePoint-specific metadata (site, path, author) |
| `sam` | SAM.gov | SAM.gov acquisition data (notices, solicitations) |
| `salesforce` | Salesforce | Salesforce CRM data (accounts, contacts, opportunities) |
| `forecast` | Forecasts | Acquisition forecast data (AG, APFS, state) |
| `scrape` | Web Scrape | Web scraping metadata (URLs, collections) |
| `sync` | Sync | Sync configuration metadata |
| `file` | File | File-level metadata (extension, description, document type) |
| `custom` | AI-Generated | LLM-generated metadata bridged from AssetMetadata |

### How namespaces are populated

- **Connectors** write namespaced fields into `Asset.source_metadata` directly (e.g., SharePoint sync writes `sharepoint.site_name`, `sharepoint.folder`)
- **MetadataBuilders** pass `source_metadata` through to `search_chunks.metadata` during indexing
- **Entity builders** (SAM, Salesforce, Forecast) read from typed model columns and produce namespaced metadata
- **AssetMetadata bridge** propagates canonical LLM-generated metadata to the `custom` namespace

### Example metadata structures

```json
// SharePoint asset
{
  "source": {"storage_folder": "sharepoint/site/docs"},
  "sharepoint": {"path": "/Shared Documents/policies", "site_name": "IT Department"},
  "file": {"extension": ".pdf", "document_type": "Proposal"}
}

// SAM notice
{"sam": {"notice_id": "abc", "agency": "GSA", "notice_type": "Combined Synopsis/Solicitation"}}

// Salesforce account
{"salesforce": {"salesforce_id": "001...", "account_type": "Customer", "industry": "Tech"}}

// Forecast
{"forecast": {"source_type": "ag", "agency_name": "DOD", "fiscal_year": 2026}}
```

---

## Fields

Fields are the individual metadata properties within each namespace. Each field has a type, indexing configuration, and optional facet/filter capabilities.

**File**: `backend/app/core/metadata/registry/fields.yaml`

### Field properties

| Property | Type | Description |
|----------|------|-------------|
| `data_type` | string | `string`, `number`, `boolean`, `date`, `enum`, `array`, `object` |
| `indexed` | boolean | Whether the field is indexed in `search_chunks.metadata` |
| `facetable` | boolean | Whether the field can be used as a facet filter |
| `applicable_content_types` | array | Which content types this field appears on (e.g., `[asset]`, `[sam_notice, sam_solicitation]`) |
| `description` | string | Human-readable description |
| `examples` | array | Sample values (also used as `allowed_values` for facetable fields with >3 examples) |

### Examples of field definitions

```yaml
# String field with facet support
sharepoint:
  site_name:
    data_type: string
    indexed: true
    facetable: true
    applicable_content_types: [asset]
    description: "SharePoint site display name"
    examples: ["IT Department", "Engineering"]

# Enum-like field with prescriptive values
file:
  document_type:
    data_type: string
    indexed: true
    facetable: true
    applicable_content_types: [asset]
    description: "LLM-classified document type"
    examples:
      - "Proposal"
      - "Solicitation"
      - "White Paper"
      - "Contract"
      - "Report"
      - "Other"
```

### Content types

Content types define which records a field applies to:

| Content Type | Description |
|-------------|-------------|
| `asset` | Uploaded/synced document |
| `sam_notice` | Individual SAM.gov notice |
| `sam_solicitation` | Grouped SAM.gov solicitation |
| `ag_forecast` | GSA Acquisition Gateway forecast |
| `apfs_forecast` | DHS APFS forecast |
| `state_forecast` | State Department forecast |
| `salesforce_account` | Salesforce account |
| `salesforce_contact` | Salesforce contact |
| `salesforce_opportunity` | Salesforce opportunity |

---

## Facets

Facets are **cross-domain filter abstractions**. A single facet (e.g., "agency") maps to different JSON paths in different content types, so users can apply one filter across all data sources.

**File**: `backend/app/core/metadata/registry/facets.yaml`

### How facets work

```
User filter:  { "agency": "GSA" }
                    │
                    ▼
Facet resolution (MetadataRegistryService):
  sam_notice       → metadata->'sam'->>'agency' = 'GSA'
  sam_solicitation → metadata->'sam'->>'agency' = 'GSA'
  ag_forecast      → metadata->'forecast'->>'agency_name' = 'GSA'
  apfs_forecast    → metadata->'forecast'->>'agency_name' = 'GSA'
  asset            → metadata->'sam'->>'agency' = 'GSA'
```

A single `agency` facet produces correct SQL for each content type, even though the JSON path differs (`sam.agency` vs `forecast.agency_name`).

### Facet properties

| Property | Description |
|----------|-------------|
| `display_name` | Human-readable label (shown in UI and MCP) |
| `data_type` | Value type: `string`, `number`, `boolean`, `date` |
| `description` | Explanation of what this facet filters |
| `has_reference_data` | Whether this facet uses canonical value resolution (see [Reference Data](#reference-data)) |
| `operators` | Supported filter operators: `eq`, `in`, `gte`, `lte`, `contains`, `exists` |
| `mappings` | Maps `content_type` to `namespace.field` JSON path |

### Current facets

| Facet | Display Name | Operators | Mapped Content Types |
|-------|-------------|-----------|---------------------|
| `agency` | Agency | eq, in | SAM notices/solicitations, all forecasts, Salesforce, assets |
| `naics_code` | NAICS Code | eq, in | SAM solicitations |
| `set_aside` | Set-Aside | eq, in | SAM solicitations, all forecasts |
| `notice_type` | Notice Type | eq, in | SAM notices |
| `fiscal_year` | Fiscal Year | eq, in, gte, lte | All forecasts |
| `award_quarter` | Award Quarter | eq, in | All forecasts |
| `folder` | Folder | eq, in, contains | Assets (SharePoint) |
| `site_name` | SharePoint Site | eq, in | Assets |
| `created_by` | Created By | eq, in | Assets (SharePoint) |
| `account_type` | Account Type | eq, in | Salesforce accounts |
| `industry` | Industry | eq, in | Salesforce accounts |
| `stage_name` | Stage | eq, in | Salesforce opportunities |
| `opportunity_type` | Opportunity Type | eq, in | Salesforce opportunities |
| `collection_name` | Scrape Collection | eq, in | Assets (web scrape) |
| `file_extension` | File Type | eq, in | Assets |
| `forecast_source` | Forecast Source | eq, in | All forecasts |
| `document_type` | Document Type | eq, in | Assets |

### Using facets in search

```json
// Single value
{"query": "cybersecurity", "facet_filters": {"agency": "GSA"}}

// Multiple values (OR within facet)
{"query": "cybersecurity", "facet_filters": {"agency": ["GSA", "DHS"]}}

// Multiple facets (AND between facets)
{"query": "IT services", "facet_filters": {"agency": "GSA", "document_type": "Proposal"}}
```

Multiple values within a single facet use `IN` (OR). Multiple facets combine with `AND`.

---

## Reference Data

For facets where the same entity appears under different names across data sources, the reference data system provides **canonical value resolution**. When a user searches for "DHS", it also matches "HOMELAND SECURITY, DEPARTMENT OF" and "Dept. of Homeland Security".

**File**: `backend/app/core/metadata/registry/reference_data.yaml`

### How it works

1. Each facet with `has_reference_data: true` (currently `agency` and `set_aside`) has canonical values with aliases
2. On startup, canonical values and aliases are synced to `facet_reference_values` and `facet_reference_aliases` tables
3. When searching, the search service resolves aliases to canonicals, then matches any variant

### Example

```yaml
agency:
  - canonical: "Department of Homeland Security"
    display_label: "DHS"
    aliases:
      - value: "HOMELAND SECURITY, DEPARTMENT OF"   # SAM.gov format
        source_hint: sam_gov
      - value: "DHS"                                 # Common abbreviation
      - value: "Dept. of Homeland Security"          # Informal
```

A search for `{"agency": "DHS"}` resolves to the canonical "Department of Homeland Security" and matches all alias variants in the index.

### Discover Values flow

The admin Metadata page has a "Discover Values" button that uses LLM-assisted grouping:

1. Scans the search index for distinct values not mapped to any canonical
2. Sends unmapped values to an LLM to suggest groupings
3. Presents suggestions for admin review (approve/reject/edit)
4. Approved values become canonical with their aliases

---

## Metadata Propagation Flow

There are two metadata propagation paths:

### Path 1: Source metadata (connector-driven)

```
Connector writes Asset.source_metadata
  → e.g., {"sharepoint": {"site_name": "IT Dept", "folder": "/Shared Documents"}}

Asset is indexed by PgIndexService
  → AssetPassthroughBuilder copies source_metadata to search_chunks.metadata
  → Fields become searchable and filterable via facets
```

### Path 2: LLM-generated metadata (AssetMetadata bridge)

```
CWR function writes to AssetMetadata table
  → e.g., update_metadata(asset_id, type="tags.llm.v1", content={"tags": ["cyber"]})
  → is_canonical=True (default)

Propagation to search index
  → Canonical AssetMetadata is copied to search_chunks.metadata.custom
  → Key format: dots → underscores (tags.llm.v1 → tags_llm_v1)
  → Fields become searchable in the "custom" namespace
```

### Path 3: Source metadata via CWR function

The `update_source_metadata` function writes directly to `Asset.source_metadata` and optionally propagates to search chunks:

```
Procedure calls update_source_metadata(asset_id, namespace="file", fields={"document_type": "Proposal"})
  → Writes to Asset.source_metadata.file.document_type
  → With propagate_to_search=true, updates search_chunks.metadata.file.document_type
  → Field becomes filterable via the document_type facet
```

---

## Data Source Type Registry

The data source type registry describes what each data source IS, what it contains, and how to search it. Used by AI agents to understand available data.

**File**: `backend/app/core/metadata/registry/data_sources.yaml`

| Source Type | Display Name | Key Tools |
|-------------|-------------|-----------|
| `sam_gov` | SAM.gov | `search_solicitations`, `search_notices`, `search_assets` |
| `sharepoint` | SharePoint | `search_assets`, `sp_list_items`, `sp_get_site` |
| `forecast_ag` | GSA Acquisition Gateway | `search_forecasts` |
| `forecast_apfs` | DHS APFS | `search_forecasts` |
| `forecast_state` | State Dept Forecasts | `search_forecasts` |
| `salesforce` | Salesforce CRM | `search_salesforce` |
| `web_scrape` | Web Scraping | `search_scraped_assets` |

Each source type includes: description, data_contains, capabilities, example_questions, and search_tools with recommended filters and next steps. Admins can override any field at the org level.

---

## MetadataRegistryService

The `MetadataRegistryService` is a singleton that manages the metadata catalog.

**File**: `backend/app/core/metadata/registry_service.py`

### Key behaviors

| Behavior | Detail |
|----------|--------|
| **Loading** | Parses YAML files on first access (`_ensure_loaded`) |
| **DB seeding** | `load_baseline(session)` deletes all global records and re-inserts from YAML on startup |
| **Cache** | In-memory, 5-minute TTL per organization |
| **Org isolation** | Global baseline (org_id=NULL) + org-level overrides merged per org |
| **Cache invalidation** | Automatic on write operations; manual via `POST /metadata/cache/invalidate` |

### Facet resolution

```python
from app.core.metadata.registry_service import metadata_registry_service

# Resolve facet to JSON paths per content type
paths = metadata_registry_service.resolve_facet("agency")
# → {"sam_notice": "sam.agency", "ag_forecast": "forecast.agency_name", ...}

# Filter to specific content types
paths = metadata_registry_service.resolve_facet("agency", content_types=["sam_notice"])
# → {"sam_notice": "sam.agency"}
```

### Effective registry

```python
# Get full registry for an org (global + org overrides, cached)
registry = await metadata_registry_service.get_effective_registry(session, org_id)
# → {"namespaces": {...}, "fields": {...}, "facets": {...}}
```

---

## API Endpoints

All metadata governance endpoints are under `/api/v1/data/metadata/`.

### Read endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/catalog` | GET | Full catalog: namespaces + fields + facets with doc counts |
| `/namespaces` | GET | List all namespaces with doc counts |
| `/namespaces/{ns}/fields` | GET | Fields for a specific namespace |
| `/fields/{ns}/{field}` | GET | Single field definition |
| `/fields/{ns}/{field}/stats` | GET | Sample values and doc count for a field |
| `/facets` | GET | All facets with cross-domain mappings |
| `/facets/{name}/mappings` | GET | Mappings for a specific facet |
| `/data-sources` | GET | Data source type catalog (with org overrides) |

### Write endpoints (org-level overrides)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/fields/{ns}` | POST | Create org-level field definition |
| `/fields/{ns}/{field}` | PATCH | Update org-level field |
| `/fields/{ns}/{field}` | DELETE | Deactivate (soft-delete) org-level field |
| `/facets` | POST | Create org-level facet with mappings |
| `/facets/{name}` | PATCH | Update org-level facet |
| `/facets/{name}` | DELETE | Deactivate org-level facet |
| `/facets/{name}/mappings` | POST | Add content type mapping to facet |
| `/facets/{name}/mappings/{type}` | DELETE | Remove content type mapping |
| `/data-sources/{type}` | PATCH | Override data source type for org |

### Reference data endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/facets/{name}/autocomplete?q=` | GET | Autocomplete suggestions across canonical values and aliases |
| `/facets/{name}/reference-values` | GET | List canonical values and aliases |
| `/facets/{name}/reference-values` | POST | Create canonical value |
| `/facets/{name}/reference-values/{id}` | PATCH | Update canonical value |
| `/facets/{name}/reference-values/{id}` | DELETE | Deactivate canonical value |
| `/facets/{name}/reference-values/{id}/aliases` | POST | Add alias |
| `/facets/{name}/reference-values/{id}/aliases/{aid}` | DELETE | Remove alias |
| `/facets/{name}/discover` | POST | AI-powered: scan for unmapped values, suggest groupings |
| `/facets/{name}/reference-values/{id}/approve` | POST | Approve suggested value |
| `/facets/{name}/reference-values/{id}/reject` | POST | Reject suggested value |
| `/facets/pending-suggestions` | GET | Count of pending suggestions (for admin badge) |

### Cache management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/cache/invalidate` | POST | Force cache invalidation for current org |

---

## Admin UI

The metadata catalog is managed through the admin interface at `/admin/metadata`.

### Catalog view

Shows all namespaces and their fields, with document counts indicating how many indexed records contain each namespace.

### Facet management

Lists all facets with their cross-domain mappings. For facets with `has_reference_data: true`, provides:

- **Reference values**: List of canonical values with aliases
- **Discover Values**: LLM-assisted flow to find unmapped values in the index and suggest canonical groupings
- **Pending suggestions**: Badge count for values awaiting admin approval

### Field statistics

Click into any field to see sample values from the live index, doc counts, and cardinality.

---

## MCP / AI Agent Discovery

AI agents (via MCP Gateway or Open WebUI) discover metadata through the `discover_metadata` CWR function.

### Basic discovery (facets only)

```json
// Agent calls: discover_metadata()
// Returns:
{
  "facets": [
    {
      "name": "document_type",
      "display_name": "Document Type",
      "data_type": "string",
      "description": "Document classification ...",
      "operators": ["eq", "in"],
      "content_types": ["asset"]
    }
  ],
  "usage_hint": "Use facet_filters in search functions: {\"agency\": \"GSA\"}"
}
```

### Detailed discovery (fields + allowed values)

```json
// Agent calls: discover_metadata(include_fields=true, namespace="file")
// Returns facets PLUS:
{
  "namespaces": [
    {
      "namespace": "file",
      "display_name": "File",
      "fields": [
        {
          "name": "document_type",
          "data_type": "string",
          "facetable": true,
          "description": "LLM-classified document type",
          "examples": ["Proposal", "Solicitation", "White Paper", ...],
          "allowed_values": ["Proposal", "Solicitation", "White Paper", ...]
        }
      ]
    }
  ]
}
```

The `allowed_values` field is returned for facetable fields with more than 3 examples. Agents use this to construct valid `facet_filters` for search queries.

### Data source discovery

Agents call `discover_data_sources` to understand what data is available and which tools to use for each source type.

---

## How-To Guides

### Add a new metadata field

Edit `backend/app/core/metadata/registry/fields.yaml`:

```yaml
file:
  # Add under the appropriate namespace
  sensitivity_level:
    data_type: string
    indexed: true
    facetable: true
    applicable_content_types: [asset]
    description: "Document sensitivity classification"
    examples: ["Public", "Internal", "Confidential", "Restricted"]
```

Restart the backend. The field is immediately available in the metadata catalog API and admin UI.

### Add a new facet

Edit `backend/app/core/metadata/registry/facets.yaml`:

```yaml
sensitivity_level:
  display_name: "Sensitivity"
  data_type: string
  description: "Document sensitivity classification"
  operators: [eq, in]
  mappings:
    asset: "file.sensitivity_level"
```

Restart the backend. The facet is immediately available for search filtering.

### Add a new namespace

1. Add to `backend/app/core/metadata/registry/namespaces.yaml`:

```yaml
custom_ns:
  display_name: "My Namespace"
  description: "Custom namespace for org-specific metadata"
```

2. Add fields in `fields.yaml` under the new namespace key
3. Optionally add facets mapping to the new namespace fields
4. Restart the backend

### Add reference data for a facet

1. Set `has_reference_data: true` on the facet in `facets.yaml`
2. Add canonical values and aliases in `reference_data.yaml`:

```yaml
my_facet:
  - canonical: "Canonical Name"
    display_label: "Short"
    aliases:
      - value: "variant 1"
        source_hint: sam_gov
      - value: "variant 2"
```

3. Or use the admin UI "Discover Values" flow to find and map values from live data

### Create a classification procedure (zero code)

See `backend/app/cwr/procedures/store/definitions/classify_documents.json` for a working example that:

1. Searches for assets
2. Fetches document content
3. Classifies via `llm_classify` with prescriptive categories
4. Persists results to `source_metadata` via `update_source_metadata`
5. Propagates to search index for facet filtering

To create a new classification dimension, define the field + facet in YAML and create a new procedure JSON with the appropriate categories.

---

## Key Files

| File | Purpose |
|------|---------|
| `backend/app/core/metadata/registry/namespaces.yaml` | Namespace definitions |
| `backend/app/core/metadata/registry/fields.yaml` | Field definitions per namespace |
| `backend/app/core/metadata/registry/facets.yaml` | Cross-domain facet definitions and mappings |
| `backend/app/core/metadata/registry/reference_data.yaml` | Canonical values and aliases for reference-data facets |
| `backend/app/core/metadata/registry/data_sources.yaml` | Data source type descriptions for AI discovery |
| `backend/app/core/metadata/registry_service.py` | MetadataRegistryService — loads, caches, resolves registry |
| `backend/app/core/metadata/facet_reference_service.py` | Reference data CRUD, alias resolution, LLM discover |
| `backend/app/api/v1/data/routers/metadata.py` | REST API endpoints for metadata governance |
| `backend/app/api/v1/data/schemas.py` | Pydantic models for metadata API |
| `backend/app/core/search/pg_search_service.py` | Facet resolution in search queries |
| `backend/app/core/search/metadata_builders.py` | MetadataBuilder registry for indexing |
| `backend/app/core/shared/asset_metadata_service.py` | AssetMetadata CRUD (LLM-generated metadata) |
| `backend/app/cwr/tools/primitives/search/discover_metadata.py` | CWR function for AI agent discovery |
| `backend/app/core/database/models.py` | ORM models: MetadataFieldDefinition, FacetDefinition, FacetMapping |

---

## Related Documentation

| Document | Description |
|----------|-------------|
| [Search & Indexing](SEARCH_INDEXING.md) | Hybrid search, chunking, embeddings, metadata filtering |
| [Functions & Procedures](FUNCTIONS_PROCEDURES.md) | CWR workflow automation (procedures that use metadata) |
| [Configuration](CONFIGURATION.md) | Environment and YAML config |
| [API Documentation](API_DOCUMENTATION.md) | Complete API reference |
| [MCP Gateway](../mcp/README.md) | AI tool server and MCP protocol |
