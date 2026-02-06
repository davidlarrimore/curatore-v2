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

**Location**: `backend/app/functions/content/content_item.py`

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

**Location**: `backend/app/functions/content/service.py`

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

**Location**: `backend/app/functions/base.py`

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

**Location**: `backend/app/functions/context.py`

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
| **LLM** (`llm/`) | `generate`, `extract`, `summarize`, `classify`, `decide`, `route` | LLM-powered analysis |
| **Search** (`search/`) | `search_assets`, `search_solicitations`, `search_notices`, `get`, `get_content`, `query_model` | Query and retrieve data |
| **Output** (`output/`) | `update_metadata`, `bulk_update_metadata`, `create_artifact`, `generate_document` | Create/update data |
| **Notify** (`notify/`) | `send_email`, `webhook` | External notifications |
| **Compound** (`compound/`) | `analyze_solicitation`, `summarize_solicitations`, `generate_digest`, `classify_document` | Multi-step workflows |

### Function Registry

**Location**: `backend/app/functions/registry.py`

```python
from app.functions import fn

# Get a function
func = fn.get("search_assets")

# List all functions
all_functions = fn.list_all()

# List by category
llm_functions = fn.list_by_category(FunctionCategory.LLM)
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

**Location**: `backend/app/procedures/definitions/`

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
├── functions/
│   ├── __init__.py          # fn namespace
│   ├── base.py              # BaseFunction, FunctionResult
│   ├── context.py           # FunctionContext
│   ├── registry.py          # FunctionRegistry
│   └── content/
│       ├── content_item.py  # ContentItem dataclass
│       ├── service.py       # ContentService
│       └── registry.py      # ContentTypeRegistry
│   └── llm/, search/, output/, notify/, compound/
├── procedures/
│   ├── base.py              # ProcedureDefinition
│   ├── executor.py          # ProcedureExecutor
│   ├── discovery.py         # YAML auto-discovery
│   ├── loader.py            # YAML loading with Jinja2
│   └── definitions/         # YAML procedure definitions
├── pipelines/
│   ├── executor.py          # PipelineExecutor
│   └── definitions/         # YAML pipeline definitions
├── database/
│   └── procedures.py        # Procedure, Pipeline, Trigger models
└── services/
    └── event_service.py     # Event emission
```

---

## API Endpoints

```
# Functions
GET    /api/v1/functions/                 # List all functions
GET    /api/v1/functions/categories       # List categories
GET    /api/v1/functions/{name}           # Get function details
POST   /api/v1/functions/{name}/execute   # Execute function directly

# Procedures
GET    /api/v1/procedures/                # List procedures
GET    /api/v1/procedures/{slug}          # Get procedure details
POST   /api/v1/procedures/{slug}/run      # Execute procedure
POST   /api/v1/procedures/{slug}/enable   # Enable procedure
POST   /api/v1/procedures/{slug}/disable  # Disable procedure

# Pipelines
GET    /api/v1/pipelines/                 # List pipelines
GET    /api/v1/pipelines/{slug}           # Get pipeline details
POST   /api/v1/pipelines/{slug}/run       # Execute pipeline
GET    /api/v1/pipelines/{slug}/runs/{id}/items  # Get item states

# Webhooks
POST   /api/v1/webhooks/procedures/{slug} # Trigger procedure
POST   /api/v1/webhooks/pipelines/{slug}  # Trigger pipeline
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
# backend/app/functions/llm/my_function.py
from ..base import BaseFunction, FunctionResult, FunctionMeta

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

1. Create YAML file in `backend/app/procedures/definitions/`:
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
