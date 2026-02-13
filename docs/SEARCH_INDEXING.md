# Search & Indexing

Curatore v2 provides hybrid full-text + semantic search powered by PostgreSQL with the pgvector extension. Content is chunked, embedded via OpenAI, and stored in a unified `search_chunks` table that supports keyword search, vector similarity, and a combined hybrid mode.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Indexed Content Types](#indexed-content-types)
3. [Indexing Pipeline](#indexing-pipeline)
4. [Chunking](#chunking)
5. [Embeddings](#embeddings)
6. [Database Schema](#database-schema)
7. [Search Modes](#search-modes)
8. [Hybrid Scoring](#hybrid-scoring)
9. [Incremental Reindexing](#incremental-reindexing)
10. [Batch Embedding Optimization](#batch-embedding-optimization)
11. [API Endpoints](#api-endpoints)
12. [Configuration](#configuration)
13. [Search Collections](#search-collections)
14. [External Vector Store Sync](#external-vector-store-sync)
15. [Monitoring & Health](#monitoring--health)
16. [Extending Search to New Data Sources](#extending-search-to-new-data-sources)
17. [Troubleshooting](#troubleshooting)
18. [Metadata Schema Discovery](#metadata-schema-discovery)
19. [Metadata Registry (Governance)](#metadata-registry-governance)
20. [Facet Filtering](#facet-filtering-preferred)
21. [Raw Metadata Filtering](#raw-metadata-filtering-advanced)

---

## Architecture Overview

```
Content Sources              Indexing Pipeline              Search Query
─────────────────     ──────────────────────────     ─────────────────────
                      ┌──────────┐
 Assets (documents)──>│ Chunking │──> ~1500 char chunks
 SAM Notices ────────>│ Service  │        │
 SAM Solicitations ──>└──────────┘        ▼
 Salesforce Records ─>             ┌────────────┐
 Forecasts ──────────>             │ Embedding  │──> 1536-dim vectors
 Scraped Pages ──────>             │ Service    │       │
                                   └────────────┘       ▼
                                                ┌──────────────┐
                                                │search_chunks │
                                                │  (PostgreSQL)│
                                                │              │
                                                │ tsvector ────│──> Keyword search
                                                │ vector(1536) │──> Semantic search
                                                └──────────────┘       │
                                                        ▲              ▼
                                                        │      Combined hybrid
                                                        │        ranking
                                                   Search API ◄────────┘
```

**Key components:**

| Component | File | Purpose |
|-----------|------|---------|
| PgIndexService | `backend/app/core/search/pg_index_service.py` | Index content to `search_chunks` |
| PgSearchService | `backend/app/core/search/pg_search_service.py` | Execute search queries |
| ChunkingService | `backend/app/core/search/chunking_service.py` | Split documents into chunks |
| EmbeddingService | `backend/app/core/search/embedding_service.py` | Generate OpenAI embeddings |
| Search Router | `backend/app/api/v1/data/routers/search.py` | REST API endpoints |
| Maintenance Handler | `backend/app/core/ops/maintenance_handlers.py` | Bulk reindexing |

---

## Indexed Content Types

All searchable content is stored in the `search_chunks` table with a `source_type` discriminator and a `source_type_filter` for UI filtering.

| Source Type | Filter Category | Chunked? | Description |
|-------------|----------------|----------|-------------|
| `asset` | `upload`, `sharepoint`, `web_scrape` | Yes | Documents, PDFs, web pages |
| `sam_notice` | `sam_gov` | No (single chunk) | Individual SAM.gov notice |
| `sam_solicitation` | `sam_gov` | No (single chunk) | SAM.gov solicitation group |
| `ag_forecast` | `forecast` | No (single chunk) | AG acquisition forecast |
| `apfs_forecast` | `forecast` | No (single chunk) | APFS acquisition forecast |
| `state_forecast` | `forecast` | No (single chunk) | State acquisition forecast |
| `salesforce_account` | `salesforce` | No (single chunk) | Salesforce account |
| `salesforce_contact` | `salesforce` | No (single chunk) | Salesforce contact |
| `salesforce_opportunity` | `salesforce` | No (single chunk) | Salesforce opportunity |

**Assets** are the only content type that gets chunked into multiple pieces. All other types produce a single chunk per record because their content is short enough to embed as a single text.

---

## Indexing Pipeline

### Per-Item Indexing (real-time)

When a document is uploaded or a record is synced, it is indexed immediately:

```
1. Content Assembly
   - Assets: Download markdown from MinIO, extract title/filename
   - SAM/Salesforce/Forecasts: Build content string from model fields

2. Chunking (assets only)
   - Split into ~1500 char chunks with 200 char overlap
   - Non-asset types use the full content as a single chunk

3. Embedding Generation
   - Call OpenAI text-embedding-3-small API
   - Returns 1536-dimensional vector per chunk

4. Database Insert
   - INSERT INTO search_chunks with ON CONFLICT (upsert)
   - PostgreSQL trigger auto-populates tsvector from content
   - Delete any orphaned chunks (if chunk count decreased)

5. Timestamp Update
   - Set indexed_at = NOW() on source record
   - Also set updated_at = NOW() to prevent reindex race condition
```

### Bulk Reindexing (maintenance task)

The `search.reindex` maintenance handler reprocesses all content. See [Incremental Reindexing](#incremental-reindexing).

---

## Chunking

The `ChunkingService` splits long documents into chunks optimized for semantic search. Embeddings work best on coherent, focused text segments rather than entire documents.

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_CHUNK_SIZE` | 1500 chars | Target maximum chunk size |
| `MIN_CHUNK_SIZE` | 100 chars | Minimum to form a standalone chunk |
| `OVERLAP_SIZE` | 200 chars | Overlap between consecutive chunks |

### Algorithm

1. **Normalize**: Fix line endings, collapse excessive blank lines and spaces
2. **Paragraph split**: Split on double newlines (paragraph boundaries)
3. **Merge small paragraphs**: Accumulate paragraphs until `MAX_CHUNK_SIZE` is reached
4. **Split large paragraphs**: Break at sentence boundaries (`(?<=[.!?])\s+(?=[A-Z])`)
5. **Word-level fallback**: If a single sentence exceeds `MAX_CHUNK_SIZE`, split at word boundaries
6. **Add overlap**: Prepend the last 200 chars of the previous chunk to the next chunk (at word boundaries)
7. **Filter**: Discard chunks smaller than `MIN_CHUNK_SIZE` unless it's the only chunk

### Why overlap matters

Without overlap, information near chunk boundaries could be missed by search. The 200-character overlap ensures that content at the boundary of chunk N is also present in chunk N+1, so a search query matching that region will find at least one chunk.

### Example

A 5000-character document with 10 paragraphs produces ~3-4 chunks:
- Chunk 0: chars 0-1500 (paragraphs 1-4)
- Chunk 1: chars 1300-2800 (200 char overlap + paragraphs 5-7)
- Chunk 2: chars 2600-4100 (200 char overlap + paragraphs 8-9)
- Chunk 3: chars 3900-5000 (200 char overlap + paragraph 10)

---

## Embeddings

### Model

| Setting | Value |
|---------|-------|
| Default model | `text-embedding-3-small` |
| Dimensions | 1536 |
| Cost | ~$0.02 per 1M tokens |
| Max input | 8191 tokens (~30,000 chars) |
| Provider | OpenAI API |

The model is configurable via `config.yml` under `llm.models.embedding.model`. Supported models:

| Model | Dimensions |
|-------|-----------|
| `text-embedding-3-small` | 1536 |
| `text-embedding-3-large` | 3072 |
| `text-embedding-ada-002` | 1536 |

### Batch Processing

The `EmbeddingService` batches texts for efficient API usage:

- **Batch size**: 50 texts per API call (internal to `get_embeddings_batch()`)
- **Text truncation**: Each text capped at 8,000 chars to stay within token limits
- **Fallback**: If a batch request fails, retries texts individually
- **Error handling**: Returns a zero vector for any text that fails embedding

### Important: Embedding Determinism

OpenAI's embedding API generates the **exact same vector** for a given text regardless of whether it's sent alone or in a batch. There is no cross-attention or context bleed between batch items. Batching is purely a throughput optimization.

---

## Database Schema

### `search_chunks` Table

Created by migration `20260201_0900_add_pgvector_search.py`. Requires the `pgvector` PostgreSQL extension.

```sql
CREATE TABLE search_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type     VARCHAR(50) NOT NULL,     -- 'asset', 'sam_notice', etc.
    source_id       UUID NOT NULL,            -- FK to source entity
    organization_id UUID NOT NULL,            -- Multi-tenancy
    chunk_index     INTEGER NOT NULL DEFAULT 0,
    content         TEXT NOT NULL,            -- Chunk text
    title           TEXT,                     -- Document/entity title
    filename        VARCHAR(500),             -- Original filename
    url             VARCHAR(2048),            -- URL for web scrapes
    search_vector   tsvector,                 -- Auto-populated by trigger
    embedding       vector(1536),             -- OpenAI embedding
    source_type_filter VARCHAR(50),           -- UI filter: upload, sharepoint, etc.
    content_type    VARCHAR(255),             -- MIME type or entity type
    collection_id   UUID,                     -- Web scrape collection
    sync_config_id  UUID,                     -- SharePoint sync config
    metadata        JSONB,                    -- Namespaced metadata (see Metadata Namespaces below)
    created_at      TIMESTAMP DEFAULT NOW(),

    UNIQUE (source_type, source_id, chunk_index)
);
```

### Indexes

| Index | Type | Purpose |
|-------|------|---------|
| `uq_search_chunks_source` | UNIQUE B-tree | Dedup: (source_type, source_id, chunk_index) |
| `ix_search_chunks_org` | B-tree | Organization filtering |
| `ix_search_chunks_source` | B-tree | Source lookups (source_type, source_id) |
| `ix_search_chunks_fts` | GIN | Full-text search on `search_vector` |
| `ix_search_chunks_embedding` | IVFFlat | Vector similarity (cosine ops, 100 lists) |
| `ix_search_chunks_filters` | B-tree | Filter facets (source_type_filter, content_type) |
| `ix_search_chunks_collection` | Partial B-tree | Collection filtering (WHERE collection_id IS NOT NULL) |
| `ix_search_chunks_sync_config` | Partial B-tree | Sync config filtering (WHERE sync_config_id IS NOT NULL) |
| `ix_search_chunks_metadata_gin` | GIN (jsonb_path_ops) | Namespaced metadata containment queries |

### Full-Text Search Trigger

A PostgreSQL trigger automatically computes `search_vector` on every INSERT/UPDATE:

```sql
NEW.search_vector :=
    setweight(to_tsvector('english', COALESCE(NEW.title, '')), 'A') ||
    setweight(to_tsvector('english', COALESCE(NEW.filename, '')), 'B') ||
    setweight(to_tsvector('english', COALESCE(NEW.content, '')), 'C');
```

**Weight priorities**: Title matches (A) rank highest, filename matches (B) rank medium, content matches (C) rank lowest.

### `indexed_at` Column on Source Tables

Each indexable model has an `indexed_at` timestamp column used for incremental reindexing:

| Table | Has `indexed_at` | Has `updated_at` | Incremental Strategy |
|-------|-----------------|-----------------|---------------------|
| `assets` | Yes | Yes | Reindex when `indexed_at < updated_at` |
| `sam_solicitations` | Yes | Yes | Reindex when `indexed_at < updated_at` |
| `sam_notices` | Yes | No (immutable) | Reindex only when `indexed_at IS NULL` |
| `salesforce_accounts` | Yes | Yes | Reindex when `indexed_at < updated_at` |
| `salesforce_contacts` | Yes | Yes | Reindex when `indexed_at < updated_at` |
| `salesforce_opportunities` | Yes | Yes | Reindex when `indexed_at < updated_at` |
| `ag_forecasts` | Yes | Yes | Reindex when `indexed_at < updated_at` |
| `apfs_forecasts` | Yes | Yes | Reindex when `indexed_at < updated_at` |
| `state_forecasts` | Yes | Yes | Reindex when `indexed_at < updated_at` |

**Important implementation detail**: When setting `indexed_at`, the code also explicitly sets `updated_at` to the same timestamp value. This prevents SQLAlchemy's `onupdate=datetime.utcnow` from creating a sub-millisecond gap where `updated_at` would be slightly later than `indexed_at`, which would cause every item to appear as needing reindexing.

---

## Metadata Namespaces

The `search_chunks.metadata` column uses **nested JSONB namespaces** to organize metadata by source type. This prevents key collisions across different source types and enables efficient querying via PostgreSQL's JSONB operators.

### Namespace Convention

| Namespace | Used By | Description |
|-----------|---------|-------------|
| `source` | All assets | Common fields: `storage_folder`, `uploaded_by` |
| `sharepoint` | SharePoint assets | `path`, `folder`, `web_url`, `created_by`, `modified_by` |
| `sam` | SAM notices & solicitations | `notice_id`, `agency`, `posted_date`, `naics_code`, etc. |
| `salesforce` | Salesforce entities | `salesforce_id`, `account_type`, `stage_name`, etc. |
| `forecast` | Acquisition forecasts | `source_type`, `agency_name`, `fiscal_year`, etc. |
| `custom` | LLM-generated metadata | Bridged from `AssetMetadata` table (e.g., `tags_llm_v1`, `summary_short_v1`) |

### Examples

```json
// Asset (SharePoint)
{
  "source": {"storage_folder": "sharepoint/site/docs"},
  "sharepoint": {"path": "/Shared Documents/policies", "folder": "/Shared Documents", "web_url": "https://..."},
  "custom": {"tags_llm_v1": {"tags": ["contract"]}}
}

// SAM Notice
{"sam": {"notice_id": "abc", "notice_type": "Combined", "agency": "GSA", "posted_date": "2026-01-01"}}

// Salesforce Account
{"salesforce": {"salesforce_id": "001...", "account_type": "Customer", "industry": "Tech"}}

// Forecast
{"forecast": {"source_type": "ag", "agency_name": "DOD", "fiscal_year": 2026}}
```

### Querying Namespaced Metadata

Use PostgreSQL's JSONB arrow operators to access nested values:

```sql
-- Filter by SAM agency
SELECT * FROM search_chunks
WHERE metadata->'sam'->>'agency' = 'GSA';

-- Filter by forecast fiscal year
SELECT * FROM search_chunks
WHERE (metadata->'forecast'->>'fiscal_year')::int = 2026;

-- Filter by storage folder prefix
SELECT * FROM search_chunks
WHERE metadata->'source'->>'storage_folder' LIKE 'sharepoint/%';

-- Check for custom metadata existence
SELECT * FROM search_chunks
WHERE metadata->'custom' ? 'tags_llm_v1';
```

### MetadataBuilder Registry

Metadata is built consistently by the `MetadataBuilder` registry (`backend/app/core/search/metadata_builders.py`). Each source type has a registered builder that produces both indexable content and namespaced metadata. See [Extending Search](#extending-search-to-new-data-sources) for how to add builders for new source types.

**Asset builders** use a pass-through pattern: connectors write namespaced `Asset.source_metadata` directly, and `AssetPassthroughBuilder` returns it as-is. Entity builders (SAM, Salesforce, Forecast) still read from typed model columns and produce namespaced metadata.

### Custom Namespace (AssetMetadata Bridge)

When canonical metadata is created via `update_metadata` or `bulk_update_metadata` functions (with `is_canonical=True` default), it is automatically propagated to the `custom` namespace in `search_chunks.metadata`. This makes LLM-generated metadata searchable and filterable without a separate query path.

The key format is the metadata type with dots replaced by underscores: `tags.llm.v1` becomes `tags_llm_v1`.

### Metadata Registry (Governance)

Metadata fields and facets are formally defined in a DB-backed registry:

| Table | Purpose |
|-------|---------|
| `metadata_field_definitions` | All known fields per namespace with types, indexing, facet flags |
| `facet_definitions` | Cross-domain facet definitions with supported operators |
| `facet_mappings` | Maps each facet to a `json_path` per `content_type` |

**YAML baseline** (`backend/app/core/metadata/registry/`): Global field and facet definitions loaded at startup. Org-level overrides stored in DB.

**MetadataRegistryService** (`backend/app/core/metadata/registry_service.py`): Singleton that loads YAML baseline, seeds DB tables, resolves effective registry per org (5-min TTL cache).

**Governance APIs** at `/api/v1/data/metadata/`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/catalog` | GET | Full catalog: namespaces, fields, facets |
| `/namespaces` | GET | List namespaces with doc counts |
| `/namespaces/{ns}/fields` | GET | Fields in a namespace |
| `/fields/{ns}/{field}/stats` | GET | Sample values, cardinality |
| `/facets` | GET | List all facets with mappings |

---

## Search Modes

### Keyword Search (`keyword`)

Uses PostgreSQL's built-in full-text search (`tsvector` + `tsquery`).

- **How it works**: Query is parsed into a `tsquery` with prefix matching (e.g., `"government contracts"` becomes `government:* & contracts:*`)
- **Scoring**: `ts_rank()` function with weighted fields (title > filename > content)
- **Highlighting**: `ts_headline()` generates snippets with `<mark>` tags around matches
- **Best for**: Exact term matching, known keywords, specific phrases

### Semantic Search (`semantic`)

Uses pgvector cosine similarity on OpenAI embeddings.

- **How it works**: Query text is embedded via OpenAI API, then compared against stored embeddings using cosine distance (`<=>` operator)
- **Scoring**: `1 - cosine_distance` (0 to 1 scale)
- **Threshold**: Minimum 0.3 similarity to be included in results
- **Index**: IVFFlat with 100 lists scans the nearest approximate neighbors
- **Best for**: Conceptual/semantic queries, finding related content, natural language questions

### Hybrid Search (`hybrid`) — Default

Combines keyword and semantic results with configurable weighting.

- **How it works**: Runs both searches in parallel (as CTEs), then combines scores
- **Best for**: Most queries — catches both exact matches and semantically related content

---

## Hybrid Scoring

The hybrid search combines keyword and semantic scores using a configurable weight:

```
combined_score = (1 - semantic_weight) × keyword_score + semantic_weight × semantic_score
```

| `semantic_weight` | Behavior |
|-------------------|----------|
| `0.0` | Pure keyword search (fast, exact matches only) |
| `0.3` | Keyword-heavy hybrid |
| `0.5` | Equal weight (default) |
| `0.7` | Semantic-heavy hybrid |
| `1.0` | Pure semantic search (understanding-based) |

### SQL Implementation

```sql
WITH keyword_results AS (
    SELECT source_id, ts_rank(search_vector, query) as keyword_score
    FROM search_chunks
    WHERE search_vector @@ to_tsquery('english', :query)
),
semantic_candidates AS (
    SELECT source_id, 1 - (embedding <=> :query_embedding) as semantic_score
    FROM search_chunks
    WHERE 1 - (embedding <=> :query_embedding) > 0.3
    ORDER BY embedding <=> :query_embedding
    LIMIT 200
),
combined AS (
    SELECT COALESCE(k.source_id, s.source_id),
           :kw_weight * COALESCE(k.keyword_score, 0) +
           :sem_weight * COALESCE(s.semantic_score, 0) as score
    FROM keyword_results k
    FULL OUTER JOIN semantic_candidates s ON k.source_id = s.source_id
)
SELECT * FROM combined ORDER BY score DESC LIMIT :limit
```

Results from keyword and semantic are combined via `FULL OUTER JOIN`, so items found by either method appear in results. Items found by both methods receive a boosted combined score.

---

## Incremental Reindexing

The `search.reindex` maintenance task supports incremental mode to avoid re-embedding unchanged content.

### How It Works

The `_needs_reindex_filter()` function determines which items need reindexing:

```python
def _needs_reindex_filter(model):
    if force:
        return True  # Full reindex — process everything
    if not hasattr(model, "indexed_at"):
        return True  # Can't track — always include
    if not hasattr(model, "updated_at"):
        # Immutable model (e.g., SamNotice)
        return model.indexed_at.is_(None)  # Only if never indexed
    return or_(
        model.indexed_at.is_(None),         # Never indexed
        model.indexed_at < model.updated_at  # Changed since last index
    )
```

### Triggering from the UI

The System Maintenance tab at `/admin` provides controls for search reindex:

| Option | Config Key | Effect |
|--------|-----------|--------|
| Full Reindex | `force: true` | Reindex everything regardless of `indexed_at` |
| Incremental | `force: false` | Only reindex new or modified items |
| Data Sources | `data_sources` | Select which types: `assets`, `sam`, `salesforce`, `forecasts` |

### Phase Processing Order

The reindex processes content in 9 phases, grouped by data source selection:

1. **Assets** (`data_sources` includes `"assets"`) — Assets with `status='ready'`
2. **SAM Solicitations** (`"sam"`) — All solicitations for the org
3. **SAM Notices** (`"sam"`) — Linked + standalone notices
4. **Salesforce Accounts** (`"salesforce"`)
5. **Salesforce Contacts** (`"salesforce"`)
6. **Salesforce Opportunities** (`"salesforce"`)
7. **AG Forecasts** (`"forecasts"`)
8. **APFS Forecasts** (`"forecasts"`)
9. **State Forecasts** (`"forecasts"`)

### Progress Tracking

- **Heartbeat**: Every 30 seconds, the handler commits a progress update to prevent the inactivity timeout (300s threshold)
- **Phase logging**: Start and completion log events for each phase with indexed/failed counts
- **Run progress**: Current item count and phase name visible in the Job Monitor

### Celery Time Limits

The `execute_scheduled_task_async` Celery task has a 60-minute soft time limit and 65-minute hard limit. For very large datasets, a full reindex should complete within this window.

---

## Batch Embedding Optimization

For non-asset content types during bulk reindexing, content strings are collected into batches of 50 and embedded in a single OpenAI API call, rather than one call per item.

### Before (N API calls)

```
Item 1 → build content → embed (API call) → index
Item 2 → build content → embed (API call) → index
Item 3 → build content → embed (API call) → index
...
```

### After (N/50 API calls)

```
Items 1-50 → build 50 content strings → embed batch (1 API call) → index each with pre-computed embedding
Items 51-100 → build 50 content strings → embed batch (1 API call) → index each with pre-computed embedding
...
```

### Performance Impact

| Content Type | Items | Before | After | Speedup |
|-------------|-------|--------|-------|---------|
| SAM notices | 5000 | 5000 API calls (~25 min) | 100 API calls (~30s) | ~50x |
| Salesforce | 500 | 500 API calls (~2.5 min) | 10 API calls (~3s) | ~50x |
| Forecasts | 1000 | 1000 API calls (~5 min) | 20 API calls (~6s) | ~50x |
| Assets | 1200 | 1200 API calls (~6 min) | 1200 API calls (~6 min) | 1x (unchanged) |

Asset indexing is not batched across items because each asset requires downloading markdown from object storage and chunking before embedding. Assets already batch their own chunks within each call.

### Implementation

Each `index_*()` method in `PgIndexService` accepts an optional `embedding` parameter. When provided, the method skips the OpenAI API call and uses the pre-computed embedding:

```python
async def index_sam_notice(self, session, notice_id, embedding=None):
    content = f"{notice.title}\n\n{notice.description}"
    if embedding is None:
        embedding = await embedding_service.get_embedding(content)
    # ... insert chunk with embedding
```

The maintenance handler's `_build_content_for_item()` function mirrors the content-building logic in each `index_*()` method to pre-compute content strings for batch embedding.

---

## API Endpoints

### General Search

```
POST /api/v1/search
```

**Request body:**
```json
{
    "query": "government contract services",
    "search_mode": "hybrid",
    "semantic_weight": 0.5,
    "source_types": ["upload", "sam_gov"],
    "facet_filters": {"agency": "GSA"},
    "limit": 20,
    "offset": 0,
    "include_facets": true
}
```

**Response:**
```json
{
    "total": 42,
    "limit": 20,
    "offset": 0,
    "query": "government contract services",
    "hits": [
        {
            "asset_id": "uuid",
            "score": 87.5,
            "title": "Contract Requirements",
            "filename": "requirements.pdf",
            "source_type": "Document",
            "content_type": "application/pdf",
            "highlights": {
                "content": ["...federal <mark>government</mark> <mark>contract</mark>..."]
            },
            "keyword_score": 0.82,
            "semantic_score": 0.91
        }
    ],
    "facets": {
        "source_type": {
            "values": [{"value": "upload", "count": 30}, {"value": "sam_gov", "count": 12}]
        }
    }
}
```

### Domain-Specific Search

```
POST /api/v1/search/sam          # SAM.gov notices + solicitations
POST /api/v1/search/salesforce   # Salesforce accounts, contacts, opportunities
POST /api/v1/search/forecasts    # Acquisition forecasts
```

### Metadata Schema Discovery

```
GET /api/v1/search/metadata-schema
```

Returns the available metadata namespaces, their fields, sample values, and document counts. Useful for building dynamic filter UIs and for LLM procedure generation.

**Response:**
```json
{
    "namespaces": {
        "sam": {
            "display_name": "SAM.gov",
            "source_types": ["sam_notice", "sam_solicitation"],
            "doc_count": 342,
            "fields": {
                "agency": {
                    "type": "string",
                    "sample_values": ["GSA", "DOD", "HHS"],
                    "filterable": true
                },
                "notice_type": {
                    "type": "string",
                    "sample_values": ["Combined Synopsis/Solicitation", "Presolicitation"],
                    "filterable": true
                }
            }
        },
        "custom": {
            "display_name": "Custom (LLM-generated)",
            "source_types": ["asset"],
            "doc_count": 150,
            "fields": {
                "tags_llm_v1": {
                    "type": "object",
                    "sample_values": [],
                    "filterable": true
                }
            }
        }
    },
    "total_indexed_docs": 1500,
    "cached_at": "2026-02-07T12:00:00Z"
}
```

**Caching:** Schema responses are cached in-memory for 5 minutes. The cache is automatically invalidated when documents are indexed (via `index_asset()`, `index_asset_prepared()`, `propagate_asset_metadata()`) or after a full reindex. The schema structure comes from the `MetadataRegistryService` (DB-backed registry with YAML baseline), while sample values use lightweight targeted SQL queries (~250ms cold, <5ms warm).

### Facet Filtering (Preferred)

The search endpoint accepts a `facet_filters` parameter for cross-domain filtering. Facets are resolved by the `MetadataRegistryService` — each facet maps to different JSON paths across content types:

```json
{
    "query": "cybersecurity assessment",
    "facet_filters": {
        "agency": "GSA",
        "naics_code": ["541512", "541519"]
    }
}
```

This resolves `agency` to `sam.agency` for SAM data and `forecast.agency_name` for forecasts, building SQL conditions automatically. Facet definitions (names, operators, mappings) are managed via the metadata registry. Multiple facets combine with AND; multiple values within a facet use IN.

### Raw Metadata Filtering (Advanced)

The `metadata_filters` parameter is still available for direct JSONB containment filtering using PostgreSQL's `@>` operator against the GIN index:

```json
{
    "query": "cybersecurity assessment",
    "metadata_filters": {
        "sam": {"agency": "GSA"},
        "custom": {"tags_llm_v1": {"tags": ["cyber"]}}
    }
}
```

This filters results to only chunks whose `metadata` column contains the specified nested values. Both `facet_filters` and `metadata_filters` combine with all existing filters (`source_types`, `date_from`, `content_types`, etc.).

### Admin Operations

```
GET  /api/v1/search/stats     # Index statistics (doc count, chunk count, size)
GET  /api/v1/search/health    # Search health check
POST /api/v1/search/reindex   # Trigger background reindex
```

### Search Filters

| Filter | Type | Description |
|--------|------|-------------|
| `source_types` | `string[]` | Filter by: `upload`, `sharepoint`, `web_scrape`, `sam_gov`, `salesforce`, `forecast` |
| `content_types` | `string[]` | Filter by MIME type (e.g., `application/pdf`) |
| `collection_ids` | `UUID[]` | Filter by web scrape collection |
| `sync_config_ids` | `UUID[]` | Filter by SharePoint sync config |
| `date_from` | `datetime` | Created at or after |
| `date_to` | `datetime` | Created at or before |
| `facet_filters` | `object` | Cross-domain facet filter (e.g., `{"agency": "GSA"}`) — resolved via registry |
| `metadata_filters` | `object` | Raw JSONB containment filter (e.g., `{"sam": {"agency": "GSA"}}`) |

---

## Configuration

### config.yml

```yaml
search:
  enabled: true              # Enable/disable search
  default_mode: hybrid       # keyword, semantic, or hybrid
  semantic_weight: 0.5       # 0.0 (keyword only) to 1.0 (semantic only)
  chunk_size: 1500           # Max characters per chunk
  chunk_overlap: 200         # Overlap between chunks
  max_content_length: 100000 # Truncate content over this length
  batch_size: 50             # Items per bulk indexing batch
  timeout: 30                # Search request timeout (seconds)

  # Optional: dedicated pgvector database for search workload isolation.
  # When omitted, search shares the primary application database.
  # database_url: postgresql+asyncpg://user:password@pgvector-host:5432/search_db

llm:
  api_key: ${OPENAI_API_KEY}
  base_url: https://api.openai.com/v1
  models:
    embedding:
      model: text-embedding-3-small  # 1536 dimensions
```

### Dedicated Search Database (optional)

By default, search uses the primary application database. For large-scale deployments you can isolate vector workloads on a separate pgvector instance by setting `search.database_url`:

```yaml
search:
  database_url: postgresql+asyncpg://search:password@pgvector-host:5432/search_db
  enabled: true
```

When using a dedicated search database:
- The `search_chunks` table and `pgvector` extension must exist in that database
- The primary database still stores all application tables (assets, runs, etc.)
- The `search_chunks` table has no foreign keys — it uses soft references (`source_id` + `source_type`)
- **Phase 1 (current):** This setting is config-level only and documents the intended architecture; runtime separation (using a second connection pool) is planned for Phase 2

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_KEY` | (required) | OpenAI API key for embeddings |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | API endpoint (fallback if not in config.yml) |
| `SEARCH_ENABLED` | `true` | Enable/disable search functionality |

---

## Search Collections

Search collections are **isolated vector stores** — each collection has its own `collection_chunks` table with independent embeddings, tsvector search, and flat metadata. They are fully separate from the core `search_chunks` index.

### Collection Types

| Type | Description | Use Case |
|------|-------------|----------|
| `static` | Manually curated sets of assets | Custom document groups, project-specific collections |
| `dynamic` | Auto-populated based on saved query/filter config | "All cybersecurity docs", "Recent SAM.gov notices" |
| `source_bound` | Linked to a data source entity | Scrape collection, SharePoint sync, SAM search |

### Database Schema

```
search_collections
├── id (UUID PK)
├── organization_id (FK → organizations)
├── name, slug (unique per org)
├── collection_type (static/dynamic/source_bound)
├── query_config (JSONB, for dynamic collections)
├── source_type, source_id (for source_bound)
├── is_active, item_count
├── last_synced_at
└── created_at, updated_at, created_by

collection_chunks                           ← isolated per-collection vector store
├── id (UUID PK)
├── collection_id (FK → search_collections, CASCADE)
├── chunk_index (INTEGER)
├── content (TEXT)
├── search_vector (TSVECTOR, trigger-populated)
├── embedding (vector(1536), HNSW index)
├── title (TEXT)
├── source_asset_id (UUID, provenance)
├── source_chunk_id (UUID, if copied from search_chunks)
├── metadata (JSONB, flat key/value only)
└── created_at
    UNIQUE(collection_id, source_asset_id, chunk_index)
```

### Population Methods

Collections are populated via two strategies:

| Method | Speed | Embeddings | Use Case |
|--------|-------|-----------|----------|
| **Copy from index** (`/populate`) | Fast | Reuses existing | Quick setup, existing indexed assets |
| **Fresh chunking** (`/populate/fresh`) | Slower (async) | Fresh generation | Custom chunk size/overlap, re-embed |

Both strategies are **store-agnostic** — they resolve the appropriate `CollectionStoreAdapter` and delegate all storage operations through the adapter interface.

### Store Adapter Pattern

```
                    Population Service
                    (fetch, chunk, embed)
                          │
                ┌─────────┴──────────┐
                ▼                    ▼
       PgVectorStore          ExternalVectorStore (future)
    (collection_chunks)     (Pinecone/OpenSearch via Connection)
```

- **`CollectionStoreAdapter`** ABC: `upsert_chunks()`, `search()`, `delete_by_assets()`, `clear()`, `count()`
- **`PgVectorCollectionStore`**: Local pgvector implementation (current default)
- **External adapters**: Future — will use `CollectionVectorSync` entries to route to Pinecone, OpenSearch, etc.

### API Endpoints

```
# CRUD
GET    /api/v1/data/collections              - List collections
POST   /api/v1/data/collections              - Create collection
GET    /api/v1/data/collections/{id}         - Get collection
PUT    /api/v1/data/collections/{id}         - Update collection
DELETE /api/v1/data/collections/{id}         - Delete collection (cascades chunks)

# Population
POST   /api/v1/data/collections/{id}/populate       - Copy chunks from core index
POST   /api/v1/data/collections/{id}/populate/fresh  - Async re-chunk + embed (returns run_id)
DELETE /api/v1/data/collections/{id}/assets          - Remove specific assets' chunks
POST   /api/v1/data/collections/{id}/clear           - Remove all chunks

# Vector sync targets
GET    /api/v1/data/collections/{id}/syncs   - List vector sync targets
POST   /api/v1/data/collections/{id}/syncs   - Add vector sync target
DELETE /api/v1/data/collections/{id}/syncs/{sync_id} - Remove sync target
```

### CWR Functions

- **`search_collection`**: Search within a specific collection by slug or ID (uses store adapter)
- Collections are discoverable via `discover_data_sources(source_type="search_collection")`

### Discovery Flow

Collections use the two-layer discovery pattern:

| Layer | Location | Content |
|-------|----------|---------|
| **Type definition** | `data_sources.yaml` → `search_collection` | What collections ARE, capabilities, which tools |
| **Live instances** | `search_collections` DB table | Actual collections with name, slug, item_count |

MCP agent workflow:
1. `discover_data_sources()` → sees `search_collection` type with N instances
2. Picks a collection by slug
3. `search_collection(collection="cyber-sows", query="zero trust")` → searches collection_chunks
4. `get_content(asset_ids=[...])` → reads full document text

### Service

```python
from app.core.search.collection_service import collection_service
from app.core.search.collection_population_service import collection_population_service

# Create a collection
coll = await collection_service.create_collection(
    session, org_id, name="Federal Procurement", collection_type="static"
)

# Populate from core index (sync, fast)
result = await collection_population_service.populate_from_index(
    session, coll.id, org_id, asset_ids=[uuid1, uuid2]
)

# Search within a collection (via store adapter)
from app.core.search.collection_stores import PgVectorCollectionStore
store = PgVectorCollectionStore(session)
results = await store.search(coll.id, "cybersecurity", query_embedding, "hybrid", limit=20)
```

---

## External Vector Store Sync

Collections can be synced to external vector stores (Pinecone, OpenSearch, Weaviate, Qdrant, Milvus) via the `CollectionVectorSync` pattern.

### Architecture

Each collection defaults to local pgvector (`collection_chunks` table). Adding a `CollectionVectorSync` entry enables fan-out to an external store via the Connection pattern.

```
SearchCollection ──> collection_chunks (local pgvector, default)
       │
       └──> CollectionVectorSync ──> Pinecone (via Connection)
       └──> CollectionVectorSync ──> OpenSearch (via Connection)
```

### Database Schema

```
collection_vector_syncs
├── id (UUID PK)
├── collection_id (FK → search_collections, CASCADE)
├── connection_id (FK → connections, CASCADE)
├── is_enabled, sync_status (pending/syncing/synced/failed)
├── last_sync_at, last_sync_run_id
├── error_message, chunks_synced
├── sync_config (JSONB: index name, namespace, etc.)
└── created_at, updated_at
```

### Connection Type

The `vector_store` connection type supports:
- **Providers**: pinecone, opensearch, weaviate, qdrant, milvus
- **Config**: endpoint, api_key, index_name, namespace, dimensions, metric
- Registered in `ConnectionTypeRegistry` alongside llm, extraction, etc.

---

## Monitoring & Health

### Health Check

```
GET /api/v1/search/health
```

Returns:
```json
{
    "enabled": true,
    "status": "healthy",
    "backend": "postgresql+pgvector",
    "embedding_model": "text-embedding-3-small",
    "default_mode": "hybrid"
}
```

### Index Statistics

```
GET /api/v1/search/stats
```

Returns:
```json
{
    "enabled": true,
    "status": "healthy",
    "document_count": 1500,
    "chunk_count": 4200,
    "size_bytes": 524288000
}
```

### Database Queries for Debugging

```bash
# Count chunks by source type
docker exec curatore-postgres psql -U curatore -d curatore -c \
  "SELECT source_type, COUNT(*) FROM search_chunks GROUP BY source_type ORDER BY count DESC;"

# Check indexing coverage
docker exec curatore-postgres psql -U curatore -d curatore -c \
  "SELECT COUNT(*) as total,
          COUNT(indexed_at) as indexed,
          COUNT(*) - COUNT(indexed_at) as unindexed
   FROM assets WHERE status = 'ready';"

# Check for items needing reindex (indexed_at < updated_at)
docker exec curatore-postgres psql -U curatore -d curatore -c \
  "SELECT COUNT(*) as needs_reindex
   FROM sam_solicitations
   WHERE indexed_at IS NULL OR indexed_at < updated_at;"

# Verify pgvector extension
docker exec curatore-postgres psql -U curatore -d curatore -c \
  "SELECT extversion FROM pg_extension WHERE extname = 'vector';"
```

---

## Extending Search to New Data Sources

To add a new searchable content type (e.g., "widgets"):

### 1. Create a MetadataBuilder

Define a builder in `backend/app/core/search/metadata_builders.py`:

```python
class WidgetBuilder(MetadataBuilder):
    """Builder for widgets."""
    def __init__(self):
        super().__init__(source_type="widget", namespace="widget", display_name="Widget")

    def build_content(self, *, name: str = "", description: str = "", **kwargs) -> str:
        return f"{name}\n\n{description}"

    def build_metadata(self, *, category: str = "", priority: int = 0, **kwargs) -> dict:
        return {"widget": {"category": category, "priority": priority}}

# Register it
metadata_builder_registry.register(WidgetBuilder())
```

### 2. Add index method to PgIndexService

```python
async def index_widget(self, session, widget_id, embedding=None):
    widget = await session.get(Widget, widget_id)
    builder = metadata_builder_registry.get("widget")
    content = builder.build_content(name=widget.name, description=widget.description)
    metadata = builder.build_metadata(category=widget.category, priority=widget.priority)

    if embedding is None:
        embedding = await embedding_service.get_embedding(content)

    await self._delete_chunks(session, "widget", widget_id)
    await self._insert_chunk(
        session, source_type="widget", source_id=widget_id,
        organization_id=widget.organization_id, chunk_index=0,
        content=content, title=widget.name, embedding=embedding,
        source_type_filter="widget", content_type="widget",
        metadata=metadata,
    )

    # Update indexed_at (and updated_at to same value)
    _now = datetime.utcnow()
    await session.execute(
        update(Widget).where(Widget.id == widget_id)
        .values(indexed_at=_now, updated_at=_now)
    )
    await session.commit()
```

### 3. Add `indexed_at` column to the model

```python
class Widget(Base):
    # ...
    indexed_at = Column(DateTime, nullable=True)
```

### 4. Add search method to PgSearchService

Use namespaced metadata accessors for filters:

```python
async def search_widgets(self, session, organization_id, query, category=None, ...):
    filters, params = self._build_base_filters(organization_id)
    filters.append("sc.source_type = 'widget'")
    if category:
        filters.append("sc.metadata->'widget'->>'category' = :category")
        params["category"] = category
    # Use _execute_typed_search()
```

### 5. Add API endpoint

```python
@router.post("/widgets")
async def search_widgets(request: SearchRequest, ...):
    results = await pg_search_service.search_widgets(...)
    return SearchResponse(...)
```

### 6. Add to reindex handler

Add the widget phase to `handle_search_reindex()` in `backend/app/core/ops/maintenance_handlers.py`:
- Add `"widgets": "widget"` mapping to `_phase_to_builder_key()`
- Add `_index_item()` branch for `phase_key == "widgets"`

### 7. Add display type mapper

```python
WIDGET_DISPLAY_TYPES = {"widget": "Widget"}
```

---

## Troubleshooting

### pgvector extension not installed

```
ERROR: type "vector" does not exist
```

**Fix**: Use the `pgvector/pgvector` Docker image (already configured in `docker-compose.yml`) or install the extension manually:
```sql
CREATE EXTENSION vector;
```

### Embeddings failing

```
ValueError: OPENAI_API_KEY not set
```

**Fix**: Set `OPENAI_API_KEY` in `.env` or configure `llm.api_key` in `config.yml`.

### Reindex job times out

If the job shows "timed_out" after running for a while:
- **Celery time limit**: The `execute_scheduled_task_async` task has a 60-minute soft limit. For extremely large datasets, consider running reindex per-organization.
- **Heartbeat timeout**: The handler sends a heartbeat every 30 seconds. If the worker crashes or hangs, the 300-second inactivity timeout will mark the run as timed_out.

### Reindex always processes all items (not incremental)

This was caused by a race condition where setting `indexed_at` triggered SQLAlchemy's `onupdate` on `updated_at`, making `updated_at` always slightly later. **Fixed** by explicitly setting both columns to the same timestamp value.

If you still see this, verify the fix is deployed:
```bash
docker exec curatore-postgres psql -U curatore -d curatore -c \
  "SELECT id, indexed_at, updated_at,
          indexed_at < updated_at as needs_reindex
   FROM sam_solicitations
   WHERE indexed_at IS NOT NULL
   LIMIT 5;"
```

`needs_reindex` should be `false` for items that were indexed after the fix.

### Search returns no results

1. Check that search is enabled: `GET /api/v1/search/health`
2. Check that content is indexed: `GET /api/v1/search/stats`
3. Verify the organization filter — search is scoped per-organization
4. For semantic search, verify the embedding model is accessible

### Slow search queries

1. Verify indexes exist: `\di search_chunks` in psql
2. Run `ANALYZE search_chunks` to update PostgreSQL statistics
3. For very large indexes, consider increasing IVFFlat lists (requires index rebuild)
4. Check if the query is too broad — add source_type or content_type filters

---

## Related Documentation

| Document | Description |
|----------|-------------|
| [Configuration](CONFIGURATION.md) | config.yml settings including search and LLM |
| [Maintenance Tasks](MAINTENANCE_TASKS.md) | Scheduled task system, including search.reindex |
| [Document Processing](DOCUMENT_PROCESSING.md) | Extraction pipeline that feeds indexing |
| [API Documentation](API_DOCUMENTATION.md) | Complete API reference |
| [Queue System](QUEUE_SYSTEM.md) | Celery queue architecture |
