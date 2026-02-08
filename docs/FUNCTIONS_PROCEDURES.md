# Functions, Procedures & Pipelines

Curatore's workflow automation framework for building LLM-powered workflows. This document covers the Functions Engine, Procedures, and Pipelines.

## Overview

The Functions Engine provides a unified interface for working with all content types through the **ContentItem** abstraction:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           FUNCTIONS ENGINE ARCHITECTURE                          │
└─────────────────────────────────────────────────────────────────────────────────┘

  DATA SOURCES                  CONTENT LAYER                  FUNCTIONS
      │                              │                             │
      ▼                              ▼                             ▼
┌─────────────┐            ┌─────────────────┐           ┌─────────────────┐
│   Assets    │───────────▶│   ContentItem   │◀─────────▶│  LLM Functions  │
│  (files)    │            │  (universal     │           │  (summarize,    │
├─────────────┤            │   wrapper)      │           │   classify)     │
│ Solicitations│───────────▶│                 │           ├─────────────────┤
│  (SAM.gov)  │            │   • id, type    │           │ Search Functions│
├─────────────┤            │   • text        │           │  (query, get)   │
│  Notices    │───────────▶│   • fields      │           ├─────────────────┤
│  (SAM.gov)  │            │   • metadata    │           │ Output Functions│
├─────────────┤            │   • children    │           │  (update, pdf)  │
│ Scraped     │───────────▶│                 │           └─────────────────┘
│   Assets    │            │   ContentService│
└─────────────┘            │   • get()       │
                           │   • search()    │
                           └─────────────────┘
                                    │
                                    ▼
                           ┌─────────────────┐
                           │   Procedures    │
                           │  (YAML workflows)│
                           └─────────────────┘
```

---

## ContentItem: Universal Data Wrapper

All data flows through functions as `ContentItem` objects.

**Location**: `backend/app/cwr/tools/content/content_item.py`

```python
@dataclass
class ContentItem:
    # === Identity ===
    id: str                              # UUID
    type: str                            # asset, solicitation, notice, scraped_asset
    display_type: str                    # Context-aware: "Attachment", "Opportunity"

    # === Primary Content ===
    text: Optional[str] = None           # Markdown or JSON for LLM
    text_format: str = "markdown"        # markdown, json

    # === Structured Data ===
    title: Optional[str] = None
    fields: Dict[str, Any]               # Type-specific: filename, agency, NAICS
    metadata: Dict[str, Any]             # System: source_type, timestamps

    # === Relationships ===
    children: List[ContentItem]          # Nested items (notices, attachments)
    parent_id: Optional[str] = None
    parent_type: Optional[str] = None

    # === Lazy Loading ===
    text_ref: Optional[Dict] = None      # {bucket, key} for deferred loading
```

### Content Types Supported

| Type | Model | Has Text | Children |
|------|-------|----------|----------|
| `asset` | Asset | Yes (extraction) | None |
| `solicitation` | SamSolicitation | Yes (JSON) | notices, assets |
| `notice` | SamNotice | Yes (JSON) | assets |
| `scraped_asset` | ScrapedAsset | Yes (extraction) | None |
| `scrape_collection` | ScrapeCollection | No | scraped_assets |

### fields vs metadata
- **`fields`**: Entity properties (filename, agency, NAICS code, file_size)
- **`metadata`**: System/provenance info (source_type, synced_at, classified_by)

---

## ContentService

Fetches and transforms database records into ContentItems.

**Location**: `backend/app/cwr/tools/content/service.py`

```python
class ContentService:
    async def get(
        self, session, org_id, item_type, item_id,
        include_children=True, include_text=True
    ) -> ContentItem

    async def search(
        self, session, org_id, item_type, filters,
        include_children=False, include_text=True, limit=100
    ) -> List[ContentItem]

    def extract_text(
        self, item: ContentItem,
        include_children=True, max_depth=2
    ) -> str  # For LLM consumption
```

---

## Functions

Functions are atomic units of work receiving a `FunctionContext` with access to services.

### Base Classes

**Location**: `backend/app/cwr/tools/base.py`

```python
class BaseFunction:
    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult

class FunctionResult:
    status: FunctionStatus  # SUCCESS, FAILED, PARTIAL, SKIPPED
    data: Any               # ContentItem or List[ContentItem]
    message: str
    metadata: Dict
```

### FunctionContext

**Location**: `backend/app/cwr/tools/context.py`

Provides lazy-loaded services:
- `ctx.llm_service` - LLM API access
- `ctx.search_service` - pgvector search
- `ctx.minio_service` - Object storage
- `ctx.asset_service` - Asset operations
- `ctx.content_service` - ContentItem fetching
- `ctx.run_service` - Run tracking

### Function Categories

| Category | Functions | Purpose |
|----------|-----------|---------|
| **LLM** (`primitives/llm/`) | `generate`, `extract`, `summarize`, `classify`, `decide`, `route` | LLM-powered analysis |
| **Search** (`primitives/search/`) | `search_assets`, `search_solicitations`, `search_notices`, `search_forecasts`, `get`, `get_content`, `query_model` | Query and retrieve data |
| **Output** (`primitives/output/`) | `update_metadata`, `bulk_update_metadata`, `create_artifact`, `generate_document` | Create/update data |
| **Notify** (`primitives/notify/`) | `send_email`, `webhook` | External notifications |
| **Compound** (`compounds/`) | `analyze_solicitation`, `summarize_solicitations`, `generate_digest`, `classify_document` | Multi-step workflows |

### SAM.gov Search Functions

The `search_solicitations` and `search_notices` functions support an `include_assets` parameter that also searches SAM.gov document attachments (PDFs, etc.):

```yaml
# Search notices AND their document attachments
- name: search_ai_content
  function: search_notices
  params:
    keyword: "artificial intelligence"
    search_mode: hybrid
    include_assets: true  # Also search SAM.gov attachments
```

Results include both notices/solicitations (type: `notice`/`solicitation`) and documents (type: `asset`, display: `SAM Document`).

### Facet Filtering (Preferred)

All search functions support a `facet_filters` parameter for cross-domain filtering. Facets are resolved by the metadata registry — each facet maps to different JSON paths across content types:

```yaml
# Filter by agency across SAM and forecast data
- name: search_gsa_content
  function: search_notices
  params:
    keyword: "cloud services"
    facet_filters:
      agency: "GSA"

# Filter by multiple facets
- name: search_dod_it
  function: search_solicitations
  params:
    keyword: "IT modernization"
    facet_filters:
      agency: "DOD"
      naics_code: "541512"
```

Available facets include: `agency`, `naics_code`, `set_aside`, `notice_type`, `fiscal_year`, `folder`, `created_by`, `account_type`, `industry`, `stage_name`, `collection_name`, `file_extension`, and more. Use `GET /api/v1/data/metadata/facets` to discover all facets and their mappings.

### Raw Metadata Filtering (Advanced)

All search functions also support `metadata_filters` for direct JSONB containment queries:

```yaml
# Filter assets by LLM-generated tags
- name: search_tagged_docs
  function: search_assets
  params:
    query: "security assessment"
    metadata_filters:
      custom:
        tags_llm_v1:
          tags: ["cybersecurity"]
```

The procedure generator automatically includes facet definitions when generating procedures, so AI-generated procedures prefer `facet_filters` with real facet names and values.

### Folder Path Filtering (search_assets)

The `search_assets` function supports a `folder_path` parameter to limit results to a specific storage folder. This is useful for procedures that should only search within a specific SharePoint folder, upload directory, or SAM.gov attachment path.

```yaml
# Search only within a specific SharePoint folder
- name: search_proposals
  function: search_assets
  params:
    query: "security assessment"
    folder_path: "sharepoint/my-site/shared-documents/opportunities"
    limit: 20
```

**Path format**: Use the storage path as shown in the Storage Browser or Asset Detail page. The path strips the org_id prefix automatically. Examples:
- `sharepoint/contoso/shared-documents/opps` - SharePoint folder
- `uploads/{uuid}` - Upload folder
- `scrape/amivero/pages` - Scraped pages folder
- `sam/dept-of-defense/army/solicitations` - SAM.gov attachments

**Auto-normalization**: Human-friendly paths (e.g., `Shared Documents/Opportunities`) are automatically slugified to match storage paths. You can also provide partial paths (e.g., `shared-documents/opportunities`) which will match anywhere in the folder hierarchy.

**Discovering paths**: Copy folder paths from:
- **Storage Browser** (`/storage`): Use the copy button in the breadcrumb or on individual folder rows
- **Asset Detail** (`/assets/{id}`): Use the "Folder Path" copy button in the File Details section

### Function Registry

**Location**: `backend/app/cwr/tools/registry.py`

```python
from app.cwr.tools import fn

# Get a function
func = fn.get("search_assets")

# List all functions
all_functions = fn.list_all()

# List by category
llm_functions = fn.list_by_category(FunctionCategory.LLM)
```

### Output Schemas

Functions document their return types using structured `OutputSchema` objects. This provides machine-readable documentation that:
- Helps engineers know exact field names when writing procedures
- Enables AI procedure generation to reliably use correct template references
- Allows API consumers to understand output structure programmatically

**Location**: `backend/app/cwr/tools/base.py`

```python
from app.cwr.tools.base import OutputFieldDoc, OutputSchema, OutputVariant

# Simple output (e.g., llm_generate returns a string)
output_schema = OutputSchema(
    type="str",
    description="The generated text content",
)

# Structured output (e.g., search_assets returns a list of ContentItems)
output_schema = OutputSchema(
    type="list[ContentItem]",
    description="List of matching documents",
    fields=[
        OutputFieldDoc(name="id", type="str", description="Asset UUID"),
        OutputFieldDoc(name="title", type="str", description="Full document path/title"),
        OutputFieldDoc(name="original_filename", type="str", description="File name only"),
        OutputFieldDoc(name="score", type="float", description="Relevance score"),
        OutputFieldDoc(name="snippet", type="str", description="Highlighted excerpt", nullable=True),
    ],
)

# Dual-mode output (e.g., LLM functions in single vs collection mode)
output_variants = [
    OutputVariant(
        mode="collection",
        condition="when `items` parameter is provided",
        schema=OutputSchema(
            type="list[dict]",
            description="List of results for each item",
            fields=[
                OutputFieldDoc(name="item_id", type="str", description="ID of processed item"),
                OutputFieldDoc(name="result", type="str", description="Generated text"),
                OutputFieldDoc(name="success", type="bool", description="Whether generation succeeded"),
                OutputFieldDoc(name="error", type="str", description="Error message if failed", nullable=True),
            ],
        ),
    ),
]
```

**API Response**: Output schemas are included in the `/api/v1/functions/{name}` response:

```json
{
  "name": "search_assets",
  "output_schema": {
    "type": "list[ContentItem]",
    "description": "List of matching documents",
    "fields": [
      {"name": "id", "type": "str", "description": "Asset UUID", "nullable": false},
      {"name": "title", "type": "str", "description": "Full document path/title", "nullable": false}
    ]
  },
  "output_variants": []
}
```

**Using in Templates**: The schema tells you the exact field names to use:

```yaml
steps:
  - name: search_docs
    function: search_assets
    params:
      query: "quarterly report"

  - name: send_results
    function: send_email
    params:
      subject: "Found {{ steps.search_docs | length }} documents"
      body: |
        {% for doc in steps.search_docs %}
        - {{ doc.title }} ({{ doc.original_filename }})
          Score: {{ doc.score }}
        {% endfor %}
```

---

## Procedures vs Pipelines

| Feature | Procedure | Pipeline |
|---------|-----------|----------|
| Purpose | Execute workflow steps | Process collections of items |
| Structure | Sequential steps | Multi-stage with item tracking |
| Item State | None | Per-item status and checkpoints |
| Use Cases | Digests, notifications, reports | Document classification, enrichment |

---

## Procedures

YAML-defined workflows with Jinja2 templating.

**Location**: `backend/app/cwr/procedures/store/definitions/`

### Example Procedure

```yaml
name: SAM.gov Daily Digest
slug: sam_daily_digest
description: Generate a daily digest of recent SAM.gov notices

triggers:
  - type: cron
    cron_expression: "0 8 * * 1-5"  # Weekdays 8 AM
  - type: event
    event_name: sam_pull.completed
  - type: webhook

params:
  recipients:
    type: array
    items: { type: string }
    default: ["team@company.com"]
  lookback_hours:
    type: integer
    default: 24

steps:
  - name: query_notices
    function: search_notices
    params:
      posted_within_hours: "{{ params.lookback_hours }}"
      include_text: true

  - name: summarize_each
    function: llm_summarize
    foreach: "{{ steps.query_notices }}"
    params:
      item: "{{ item }}"
      include_children: true

  - name: create_digest
    function: llm_generate
    condition: "{{ steps.query_notices | length > 0 }}"
    params:
      system_prompt: "Create an executive digest."
      user_prompt: "Summarize these opportunities: {{ steps.summarize_each }}"

  - name: send_email
    function: send_email
    params:
      to: "{{ params.recipients }}"
      subject: "SAM.gov Daily Digest - {{ now_et().strftime('%B %d, %Y') }}"
      body: "{{ steps.create_digest.text }}"
      html: true
```

### Triggers

| Type | Description |
|------|-------------|
| `cron` | Schedule-based (cron expression + optional timezone) |
| `event` | System event (e.g., `sam_pull.completed`) |
| `webhook` | HTTP POST to `/api/v1/webhooks/procedures/{slug}` |

### Step Options

| Option | Description |
|--------|-------------|
| `function` | Which function to call |
| `params` | Function parameters with Jinja2 templating |
| `condition` | Skip step if evaluates to false |
| `foreach` | Iterate over a list, `{{ item }}` available |
| `on_error` | `fail` (default), `skip`, or `continue` |

### Context Variables

| Variable | Description |
|----------|-------------|
| `{{ params.* }}` | Input parameters |
| `{{ steps.step_name }}` | Previous step result |
| `{{ item }}` | Current item in foreach |
| `{{ event.* }}` | Event trigger data |
| `{{ org_id }}` | Organization UUID |
| `{{ now() }}` | Current UTC timestamp |
| `{{ now_et() }}` | Current Eastern Time |

### Content Formatting Filters

#### `md_to_html` - Markdown to HTML Conversion

LLM functions output markdown by default. When embedding their output in HTML
contexts (emails, reports), use the `md_to_html` filter:

```yaml
steps:
  - name: generate_summary
    function: llm_summarize
    params:
      text: "{{ steps.query_data }}"

  - name: send_report
    function: send_email
    params:
      to: "{{ params.recipients }}"
      subject: "Daily Report"
      html: true
      body: |
        <html>
        <body>
          <h1>Report</h1>
          <div>{{ steps.generate_summary | md_to_html }}</div>
        </body>
        </html>
```

The filter converts:
- `# Header` → `<h1>Header</h1>`
- `**bold**` → `<strong>bold</strong>`
- `- list item` → `<ul><li>list item</li></ul>`
- Code blocks, tables, etc.

---

## Event System

Events trigger procedures and pipelines automatically:

| Event | When Emitted |
|-------|--------------|
| `sam_pull.completed` | After SAM.gov pull finishes |
| `sam_pull.group_completed` | After all SAM pull extractions complete |
| `sharepoint_sync.completed` | After SharePoint sync finishes |
| `sharepoint_sync.group_completed` | After all SharePoint extractions complete |
| `scrape.group_completed` | After web crawl + extractions complete |
| `forecast_pull.completed` | After forecast pull finishes |

---

## Key Files

```
backend/app/
├── cwr/                            # Curatore Workflow Runtime
│   ├── tools/
│   │   ├── __init__.py             # fn namespace, re-exports
│   │   ├── base.py                 # BaseFunction, FunctionResult
│   │   ├── context.py              # FunctionContext
│   │   ├── registry.py             # FunctionRegistry
│   │   ├── content/
│   │   │   ├── content_item.py     # ContentItem dataclass
│   │   │   ├── service.py          # ContentService
│   │   │   └── registry.py         # ContentTypeRegistry
│   │   ├── primitives/             # llm/, search/, output/, notify/, flow/
│   │   └── compounds/              # Multi-step compound functions
│   ├── contracts/
│   │   ├── tool_contracts.py       # ToolContract + ContractGenerator
│   │   └── validation.py           # Procedure validator
│   ├── procedures/
│   │   ├── compiler/
│   │   │   └── ai_generator.py     # AI procedure generator
│   │   ├── runtime/
│   │   │   └── executor.py         # ProcedureExecutor
│   │   └── store/
│   │       ├── definitions.py      # ProcedureDefinition
│   │       ├── loader.py           # YAML loading with Jinja2
│   │       ├── discovery.py        # YAML auto-discovery
│   │       └── definitions/        # YAML procedure definitions
│   ├── pipelines/
│   │   ├── runtime/
│   │   │   ├── definitions.py      # PipelineDefinition
│   │   │   └── executor.py         # PipelineExecutor
│   │   └── store/
│   │       ├── loader.py           # Pipeline loading
│   │       ├── discovery.py        # Pipeline discovery
│   │       └── definitions/        # YAML pipeline definitions
│   ├── governance/                 # Capability profiles, approvals
│   └── observability/              # Run queries, traces, metrics
├── core/
│   ├── database/
│   │   └── procedures.py           # Procedure, Pipeline, Trigger models
│   └── shared/
│       └── event_service.py        # Event emission
```

---

## API Endpoints

All workflow endpoints are under the `/api/v1/cwr/` namespace.

```
# Functions
GET    /api/v1/cwr/functions/                 # List all functions
GET    /api/v1/cwr/functions/categories       # List categories
GET    /api/v1/cwr/functions/{name}           # Get function details + contracts
POST   /api/v1/cwr/functions/{name}/execute   # Execute function directly

# Procedures
GET    /api/v1/cwr/procedures/                # List procedures
GET    /api/v1/cwr/procedures/{slug}          # Get procedure details
POST   /api/v1/cwr/procedures/{slug}/run      # Execute procedure
POST   /api/v1/cwr/procedures/{slug}/enable   # Enable procedure
POST   /api/v1/cwr/procedures/{slug}/disable  # Disable procedure

# Pipelines
GET    /api/v1/cwr/pipelines/                 # List pipelines
GET    /api/v1/cwr/pipelines/{slug}           # Get pipeline details
POST   /api/v1/cwr/pipelines/{slug}/run       # Execute pipeline
GET    /api/v1/cwr/pipelines/{slug}/runs/{id}/items  # Get item states

# Tool Contracts
GET    /api/v1/cwr/contracts/{function_name}  # Input/output schema for a function

# Metrics (under ops namespace)
GET    /api/v1/ops/metrics/procedures         # Procedure execution metrics

# Webhooks
POST   /api/v1/data/webhooks/procedures/{slug} # Trigger procedure
POST   /api/v1/data/webhooks/pipelines/{slug}  # Trigger pipeline
```

---

## Frontend Pages

| Page | Path | Purpose |
|------|------|---------|
| Functions | `/admin/functions` | Browse functions, view parameters, test |
| Procedures | `/admin/procedures` | Manage procedures, view runs, trigger |
| Pipelines | `/admin/pipelines` | Manage pipelines, view item states |

---

## Creating a New Function

1. Create function file in appropriate category folder:
```python
# backend/app/cwr/tools/primitives/llm/my_function.py
from ...base import BaseFunction, FunctionResult, FunctionMeta

class MyFunction(BaseFunction):
    meta = FunctionMeta(
        name="my_function",
        description="What this function does",
        category="llm",
        params={
            "input_text": {"type": "string", "required": True},
            "options": {"type": "object", "default": {}},
        }
    )

    async def execute(self, ctx, **params) -> FunctionResult:
        # Implementation
        return FunctionResult.success(data=result)
```

2. Function is auto-discovered via the registry.

---

## Creating a New Procedure

1. Create YAML file in `backend/app/cwr/procedures/store/definitions/`:
```yaml
name: My Procedure
slug: my_procedure
description: What this procedure does

triggers:
  - type: cron
    cron_expression: "0 9 * * *"

params:
  my_param:
    type: string
    default: "default_value"

steps:
  - name: step_one
    function: search_assets
    params:
      query: "{{ params.my_param }}"

  - name: step_two
    function: llm_summarize
    params:
      items: "{{ steps.step_one }}"
```

2. Procedure is auto-discovered and available via API.

---

## Governance & Safety

Functions declare governance metadata through their `FunctionMeta`:

### Side Effects Logging

Functions that modify state declare `side_effects` to enable audit logging:

```python
meta = FunctionMeta(
    name="update_metadata",
    side_effects=["write_metadata"],  # Logged in RunLogEvent
)
```

Side effects are recorded in `RunLogEvent` entries with `event_type="side_effect"`, providing an audit trail of what each procedure run modified.

### Exposure Profile

Functions that send data externally declare an `exposure_profile`:

```python
meta = FunctionMeta(
    name="send_email",
    exposure_profile="external",  # Can be blocked by org settings
)
```

The executor checks exposure profiles before running steps, allowing organizations to block externally-facing functions.

---

## Tool Contracts

Each function exposes machine-readable input/output schemas via the contracts API:

```
GET /api/v1/cwr/contracts/{function_name}
```

This returns:
- **input_schema**: JSON Schema describing parameters
- **output_schema**: Structured description of return type and fields
- **output_variants**: Different output shapes based on mode (single vs collection)

Tool contracts enable the AI procedure generator to create valid procedure YAML automatically.

---

## Payload Discipline

When building procedures that process large datasets, follow the **search → get_content → LLM** pattern:

```yaml
steps:
  # Step 1: Search returns lightweight references (no full text)
  - name: find_docs
    function: search_assets
    params:
      query: "quarterly report"
      limit: 10

  # Step 2: Load full content only for items that need it
  - name: load_content
    function: get_content
    params:
      items: "{{ steps.find_docs }}"

  # Step 3: Process with LLM
  - name: summarize
    function: llm_summarize
    params:
      items: "{{ steps.load_content }}"
```

This avoids loading full document text during search, keeping search responses fast and memory-efficient. The `get_content` function loads full text on demand from object storage.

---

## Observability

### Trace ID Propagation

Every procedure run receives a `trace_id` (UUID). Child runs inherit `parent_run_id`, enabling full lineage tracking:

```
Procedure Run (trace_id=abc)
  └── Step 1 Run (parent_run_id=abc, trace_id=abc)
  └── Step 2 Run (parent_run_id=abc, trace_id=abc)
```

### Metrics

Procedure execution metrics are available via:

```
GET /api/v1/ops/metrics/procedures?days=7
```

Returns per-function call counts, average latencies, error counts, and overall success rate. Visible in the admin Settings > Metrics tab.
