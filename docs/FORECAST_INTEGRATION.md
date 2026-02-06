# Acquisition Forecast Integration

This document describes Curatore's acquisition forecast data integration, which aggregates federal procurement forecasts from three sources into a unified view.

## Overview

The forecast integration enables organizations to track upcoming federal procurement opportunities from:

| Source | Agency | API Type | Update Frequency |
|--------|--------|----------|------------------|
| **AG** | GSA Acquisition Gateway | REST (paginated) | Real-time |
| **APFS** | DHS Procurement Forecast | REST (bulk) | Periodic |
| **State** | State Department | Excel download | Monthly |

All sources are normalized into a unified database VIEW, enabling cross-source search, filtering, and analysis.

---

## Architecture

```
                                    ┌─────────────────────────────────────┐
                                    │         Forecast Syncs              │
                                    │   (ForecastSync configurations)     │
                                    └─────────────────────────────────────┘
                                                    │
                    ┌───────────────────────────────┼───────────────────────────────┐
                    │                               │                               │
                    ▼                               ▼                               ▼
        ┌───────────────────┐           ┌───────────────────┐           ┌───────────────────┐
        │   AG Pull Service │           │  APFS Pull Service│           │ State Pull Service│
        │                   │           │                   │           │                   │
        │ • List API        │           │ • Bulk API        │           │ • Web scrape      │
        │ • Detail API      │           │ • All records     │           │ • Excel download  │
        │ • Server filters  │           │ • Client filters  │           │ • Row parsing     │
        └───────────────────┘           └───────────────────┘           └───────────────────┘
                    │                               │                               │
                    ▼                               ▼                               ▼
        ┌───────────────────┐           ┌───────────────────┐           ┌───────────────────┐
        │   ag_forecasts    │           │  apfs_forecasts   │           │  state_forecasts  │
        │      (table)      │           │      (table)      │           │      (table)      │
        └───────────────────┘           └───────────────────┘           └───────────────────┘
                    │                               │                               │
                    └───────────────────────────────┼───────────────────────────────┘
                                                    │
                                                    ▼
                                    ┌─────────────────────────────────────┐
                                    │       unified_forecasts VIEW        │
                                    │   (UNION ALL with field mapping)    │
                                    └─────────────────────────────────────┘
                                                    │
                                                    ▼
                                    ┌─────────────────────────────────────┐
                                    │         ForecastService             │
                                    │   (Cross-source query interface)    │
                                    └─────────────────────────────────────┘
```

---

## Data Sources

### 1. GSA Acquisition Gateway (AG)

**Description**: Multi-agency acquisition forecast portal maintained by GSA, covering forecasts from various federal agencies.

**API Endpoints**:
```
List:   GET https://ag-dashboard.acquisitiongateway.gov/api/v3.0/resources/forecast
Detail: GET https://ag-dashboard.acquisitiongateway.gov/api/v3.0/resources/forecast/details/{nid}
```

**Characteristics**:
- Two-phase ingestion (list + detail per record)
- Paginated (25 records per page)
- Server-side filtering by agency and award status
- No authentication required
- Rate limiting: 0.3s delay between requests

**Available Filters**:
| Filter | Type | API Support |
|--------|------|-------------|
| Agency IDs | Server-side | `filter[field_result_id_target_id]` |
| Award Status | Server-side | `filter[field_award_status_target_id]` |
| NAICS Codes | Client-side | Applied after fetch |

**Key Fields**:
- `nid`: Unique record identifier
- `agency_name`, `agency_id`: Sponsoring agency
- `naics_codes`: Array of NAICS objects `[{code, description}]`
- `acquisition_phase`: Pre-Solicitation, In Solicitation, etc.
- `award_status`: Active, Awarded, Cancelled
- `estimated_award_fy`, `estimated_award_quarter`: Timeline
- `poc_name`, `poc_email`: Primary contact
- `sbs_name`, `sbs_email`: Small business specialist
- `source_url`: Direct link to AG listing

**API Response Format**:
```json
{
  "field_result_id": [{"value": "General Services Administration", "tid": "2"}],
  "field_naics_code": [{"value": "541512 Computer Systems Design"}],
  "field_point_of_contact_name": [{"value": "John Smith"}],
  ...
}
```

---

### 2. DHS APFS (Acquisition Planning Forecast System)

**Description**: DHS-only acquisition forecast system covering all DHS components (CBP, ICE, USCIS, etc.).

**API Endpoint**:
```
Bulk: GET https://apfs-cloud.dhs.gov/api/forecast/
```

**Characteristics**:
- Single bulk API (returns all records)
- No pagination
- No server-side filtering (all filtering is client-side)
- No authentication required
- Timeout: 120 seconds

**Available Filters** (all client-side):
| Filter | Description |
|--------|-------------|
| Organizations | DHS components (CBP, ICE, USCIS, etc.) |
| Fiscal Years | Filter by FY (2025, 2026, etc.) |
| NAICS Codes | 6-digit NAICS filter |

**Key Fields**:
- `apfs_number`: Unique forecast identifier (e.g., "APFS-2026-0001")
- `apfs_id`: Numeric ID
- `component`: DHS component (CBP, ICE, USCIS, TSA, etc.)
- `naics_code`, `naics_description`: Single NAICS (not array)
- `contract_type`, `contract_vehicle`: Procurement details
- `small_business_set_aside`: Set-aside type
- `dollar_range`: Estimated value range
- `fiscal_year`, `award_quarter`: Timeline
- `pop_start_date`, `pop_end_date`: Period of performance
- `poc_name`, `poc_email`, `poc_phone`: Primary contact
- `sbs_name`, `sbs_email`, `sbs_phone`: Small business specialist

**DHS Components**:
- CBP (Customs and Border Protection)
- ICE (Immigration and Customs Enforcement)
- USCIS (Citizenship and Immigration Services)
- TSA (Transportation Security Administration)
- FEMA (Federal Emergency Management Agency)
- Secret Service
- Coast Guard
- CISA (Cybersecurity and Infrastructure Security Agency)

---

### 3. State Department Procurement Forecast

**Description**: Monthly Excel file published on the State Department website containing upcoming procurement opportunities.

**Data Source**:
```
Page:  https://www.state.gov/procurement-forecast
File:  Monthly Excel (.xlsx) download
```

**Ingestion Process**:
1. **Scrape page** for Excel link (Playwright with regex fallback)
2. **Download Excel** file
3. **Parse rows** using openpyxl
4. **Generate row_hash** for upsert: `SHA256(title + naics_code + fiscal_year + estimated_value)`

**Characteristics**:
- No API (web scraping + Excel parsing)
- Monthly update cycle
- No server-side filtering
- Row hash provides stable identifier across file updates

**Key Fields**:
- `row_hash`: Computed unique identifier
- `naics_code`: Single NAICS code
- `pop_city`, `pop_state`, `pop_country`: Place of performance (State Dept emphasis)
- `acquisition_phase`: Current phase
- `set_aside_type`: Small business set-aside
- `estimated_value`: Value range
- `fiscal_year`, `estimated_award_quarter`: Timeline
- `incumbent_contractor`: Current contractor (if any)
- `facility_clearance`: Security requirements
- `source_file`, `source_row`: Traceability to Excel

**Scraping Strategy**:
```
Primary:  Playwright (handles JavaScript rendering)
Fallback: Regex pattern matching on HTML
Patterns: .xlsx href, "procurement" + "forecast" keywords, FY patterns
```

---

## Database Schema

### ForecastSync (Configuration)

```sql
CREATE TABLE forecast_syncs (
    id UUID PRIMARY KEY,
    organization_id UUID NOT NULL REFERENCES organizations(id),

    -- Identity
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) NOT NULL,
    source_type VARCHAR(20) NOT NULL,  -- 'ag', 'apfs', 'state'

    -- Status
    status VARCHAR(20) DEFAULT 'active',  -- active, paused, archived
    is_active BOOLEAN DEFAULT TRUE,

    -- Scheduling
    sync_frequency VARCHAR(20) DEFAULT 'manual',  -- manual, hourly, daily

    -- Tracking
    last_sync_at TIMESTAMP WITH TIME ZONE,
    last_sync_status VARCHAR(50),  -- success, failed, partial
    last_sync_run_id UUID REFERENCES runs(id),

    -- Configuration
    filter_config JSONB DEFAULT '{}',
    automation_config JSONB DEFAULT '{}',

    -- Stats
    forecast_count INTEGER DEFAULT 0,

    UNIQUE (organization_id, slug)
);
```

### Source-Specific Tables

Each source has a dedicated table with source-specific fields:

| Table | Unique ID | Key Differences |
|-------|-----------|-----------------|
| `ag_forecasts` | `nid` | Multi-agency, naics_codes as JSONB array |
| `apfs_forecasts` | `apfs_number` | DHS-only, component field, single naics |
| `state_forecasts` | `row_hash` | Computed ID, place of performance emphasis |

**Common Fields** (all tables):
- `id`, `organization_id`, `sync_id`
- `title`, `description`
- `first_seen_at`, `last_updated_at`
- `change_hash`: 16-char SHA256 for change detection
- `indexed_at`: Search index timestamp
- `raw_data`: Original API/Excel response

### Unified View

The `unified_forecasts` VIEW normalizes all sources:

```sql
CREATE VIEW unified_forecasts AS
SELECT
    id, organization_id, sync_id,
    'ag' AS source_type,
    nid AS source_id,
    title, description, agency_name,
    naics_codes,  -- Already JSONB array
    ...
FROM ag_forecasts

UNION ALL

SELECT
    id, organization_id, sync_id,
    'apfs' AS source_type,
    apfs_number AS source_id,
    title, description,
    'Department of Homeland Security' AS agency_name,
    jsonb_build_array(jsonb_build_object('code', naics_code)) AS naics_codes,
    ...
FROM apfs_forecasts

UNION ALL

SELECT
    id, organization_id, sync_id,
    'state' AS source_type,
    row_hash AS source_id,
    title, description,
    'Department of State' AS agency_name,
    jsonb_build_array(jsonb_build_object('code', naics_code)) AS naics_codes,
    ...
FROM state_forecasts;
```

---

## Change Detection

All sources use hash-based change detection to avoid unnecessary updates and track history.

### Key Fields by Source

| Source | Change Detection Fields |
|--------|------------------------|
| AG | title, award_status, estimated_award_fy, estimated_award_quarter, set_aside_type, acquisition_phase |
| APFS | title, contract_status, fiscal_year, award_quarter, small_business_set_aside, dollar_range |
| State | title, acquisition_phase, fiscal_year, estimated_award_quarter, set_aside_type, estimated_value |

### Hash Computation

```python
def compute_change_hash(forecast: dict, key_fields: list) -> str:
    values = [str(forecast.get(f, '')) for f in key_fields]
    return hashlib.sha256('|'.join(values).encode()).hexdigest()[:16]
```

### Upsert Logic

1. Compute `change_hash` from key fields
2. If hash unchanged → skip update (avoid noise)
3. If hash changed:
   - Update `last_updated_at`
   - Set `indexed_at = NULL` (trigger re-indexing)
   - Append to `history` array

---

## Celery Task Integration

### Task Definition

```python
@celery_app.task(name="app.tasks.forecast_sync_task")
def forecast_sync_task(sync_id: str, organization_id: str, run_id: str):
    """Execute forecast sync based on source type."""
```

### Queue Configuration

```python
# celery_app.py
Queue("forecast", routing_key="forecast")

task_routes = {
    "app.tasks.forecast_sync_task": {"queue": "forecast"},
}
```

### Execution Flow

```
API: POST /forecasts/syncs/{id}/pull
        │
        ▼
Create Run (type="forecast_sync", status="pending")
        │
        ▼
forecast_sync_task.delay(sync_id, org_id, run_id)
        │
        ▼
[Celery Worker]
        │
        ├─ source_type == "ag"    → ag_pull_service.pull_forecasts()
        ├─ source_type == "apfs"  → apfs_pull_service.pull_forecasts()
        └─ source_type == "state" → state_pull_service.pull_forecasts()
        │
        ▼
Update sync: last_sync_at, last_sync_status
Complete run: results_summary
```

### Statistics Tracked

```json
{
  "total_fetched": 150,
  "total_processed": 142,
  "created": 12,
  "updated": 130,
  "skipped": 8,
  "errors": 0,
  "duration_seconds": 45.2
}
```

---

## API Endpoints

### Sync Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/forecasts/syncs` | List syncs |
| POST | `/api/v1/forecasts/syncs` | Create sync |
| GET | `/api/v1/forecasts/syncs/{id}` | Get sync details |
| PATCH | `/api/v1/forecasts/syncs/{id}` | Update sync |
| DELETE | `/api/v1/forecasts/syncs/{id}` | Archive sync |
| POST | `/api/v1/forecasts/syncs/{id}/pull` | Trigger manual pull |
| POST | `/api/v1/forecasts/syncs/{id}/clear` | Delete all forecasts |

### Forecasts (Unified View)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/forecasts` | List forecasts (unified) |
| GET | `/api/v1/forecasts/{id}` | Get forecast by UUID |
| GET | `/api/v1/forecasts/stats` | Dashboard statistics |

### Query Parameters

```
GET /api/v1/forecasts?
    source_type=ag,apfs      # Filter by source(s)
    sync_id={uuid}           # Filter by sync
    fiscal_year=2026         # Filter by FY
    agency_name=GSA          # Partial match
    search=cybersecurity     # Full-text search
    sort_by=last_updated_at  # Sort field
    sort_direction=desc      # Sort direction
    limit=50                 # Page size
    offset=0                 # Pagination offset
```

---

## Frontend Integration

### WebSocket-Based Updates

The frontend uses WebSocket for real-time job status updates:

```typescript
// Track forecast sync jobs
const { getJobsByType } = useUnifiedJobs()
const forecastSyncJobs = getJobsByType('forecast_sync')

// Detect job completion
useEffect(() => {
  if (forecastSyncJobs.length < prevCount) {
    loadSyncs(true) // Refresh on completion
  }
  prevJobCountRef.current = forecastSyncJobs.length
}, [forecastSyncJobs.length])
```

### Page Structure

```
/forecasts              # Main dashboard with tabs
/forecasts/browse       # Browse all forecasts
/forecasts/syncs        # Manage sync configurations
/forecasts/syncs/new    # Create new sync
/forecasts/syncs/{id}   # Sync detail with forecasts
/forecasts/{id}         # Forecast detail (UUID-based)
```

### Source Type Styling

```typescript
const sourceTypeConfig = {
  ag: {
    label: 'AG',
    color: 'blue',
    bgColor: 'bg-blue-100 dark:bg-blue-900/30',
    description: 'GSA Acquisition Gateway'
  },
  apfs: {
    label: 'DHS',
    color: 'amber',
    bgColor: 'bg-amber-100 dark:bg-amber-900/30',
    description: 'DHS APFS'
  },
  state: {
    label: 'State',
    color: 'purple',
    bgColor: 'bg-purple-100 dark:bg-purple-900/30',
    description: 'State Department'
  }
}
```

---

## Configuration Examples

### AG Sync (IT Services)

```json
{
  "name": "GSA IT Services Forecast",
  "source_type": "ag",
  "sync_frequency": "daily",
  "filter_config": {
    "agency_ids": [2],
    "naics_codes": ["541512", "541519", "541511"],
    "award_status": "Active"
  }
}
```

### APFS Sync (CBP Opportunities)

```json
{
  "name": "CBP FY26 Forecast",
  "source_type": "apfs",
  "sync_frequency": "hourly",
  "filter_config": {
    "organizations": ["CBP"],
    "fiscal_years": [2026, 2027],
    "naics_codes": ["336411", "336413"]
  }
}
```

### State Sync (With Automation)

```json
{
  "name": "State Dept Monthly",
  "source_type": "state",
  "sync_frequency": "daily",
  "filter_config": {},
  "automation_config": {
    "after_procedure_slug": "state-forecast-digest",
    "after_procedure_params": {
      "recipients": ["procurement@company.com"]
    }
  }
}
```

---

## Search Integration

Forecasts are indexed to pgvector for hybrid search:

```python
await pg_index_service.index_forecast(
    source_type=f"{source_type}_forecast",  # ag_forecast, apfs_forecast, state_forecast
    source_id=forecast_id,
    source_type_filter="forecast",  # Groups all forecast types
    content=f"{title}\n{description}\n{agency_name}",
    title=title,
    metadata={
        "source_type": source_type,
        "agency_name": agency_name,
        "source_id": source_id,
    }
)
```

Forecasts appear in unified search with filter: `source_type_filter: "forecast"`

---

## Scheduled Syncs

ForecastSync supports automatic scheduling:

| Frequency | Execution |
|-----------|-----------|
| manual | User-triggered only |
| hourly | Every hour via scheduled task |
| daily | Daily at 6:30 AM UTC |

Scheduled task handlers find syncs with matching frequency and trigger pulls:

```python
async def handle_forecast_scheduled_sync(session, run, config):
    frequency = config.get("frequency")  # "hourly" or "daily"
    syncs = await forecast_sync_service.list_syncs_by_frequency(session, frequency)
    # Trigger forecast_sync_task for each eligible sync
```

---

## Key Files

| File | Purpose |
|------|---------|
| `backend/app/database/models.py` | ForecastSync, AgForecast, ApfsForecast, StateForecast models |
| `backend/app/services/forecast_sync_service.py` | Sync configuration CRUD |
| `backend/app/services/forecast_service.py` | Unified forecast access via VIEW |
| `backend/app/services/ag_forecast_service.py` | AG record CRUD |
| `backend/app/services/ag_pull_service.py` | AG API integration |
| `backend/app/services/apfs_forecast_service.py` | APFS record CRUD |
| `backend/app/services/apfs_pull_service.py` | APFS API integration |
| `backend/app/services/state_forecast_service.py` | State record CRUD |
| `backend/app/services/state_pull_service.py` | State scraping + Excel parsing |
| `backend/app/api/v1/routers/forecasts.py` | REST API endpoints |
| `backend/app/tasks.py` | `forecast_sync_task` Celery task |
| `frontend/app/forecasts/` | Frontend pages |

---

## Troubleshooting

### AG API Issues

- **Rate limiting**: Service adds 0.3s delay between requests
- **Empty results**: Check agency_id and award_status filter values
- **Missing details**: Detail API may return incomplete data for some records

### APFS API Issues

- **Timeout**: Bulk API may timeout (120s limit) if service is slow
- **Empty response**: API occasionally returns empty array; retry usually works

### State Scraping Issues

- **Link not found**: Excel link pattern may change; check regex fallback
- **Playwright unavailable**: Falls back to regex scraping
- **Excel format changes**: Row parsing may need updates if columns change

### Common Issues

- **Sync stuck "syncing"**: Check Celery worker logs, verify run status
- **No forecasts appearing**: Verify filter_config isn't too restrictive
- **Change detection not working**: Check change_hash computation and key fields
