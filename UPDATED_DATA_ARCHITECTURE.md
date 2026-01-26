# Curatore Data Lifecycle & Processing Architecture (Pragmatic White Paper)

## Executive Summary

Curatore is evolving into a platform that ingests large volumes of heterogeneous content, automatically canonicalizes that content, enables rapid experimentation with LLM-based synthesis, and selectively synchronizes high-value outputs to downstream systems such as vector databases, Open WebUI, and external consumers.

This white paper proposes a **pragmatic, incremental architecture** that:
- Builds on Curatore’s existing frontend, backend, object store, and connection system
- Treats **content extraction as automatic platform infrastructure**, not a configurable workflow step
- Separates **import, processing, and output synchronization** into distinct concerns
- Prioritizes **experimentation speed and UX clarity** over premature workflow generalization
- Scales naturally toward automation and production pipelines when patterns stabilize

The goal is not to build a generic workflow engine, but a **curation-first system optimized for iteration, observability, and trust**.

---

## Design Principles

1. **Extraction is infrastructure**
   - Automatic, opinionated, consistent
   - Not configured per workflow

2. **Experimentation precedes automation**
   - Users must be able to test, compare, and iterate before committing to pipelines

3. **Artifacts are first-class**
   - Every meaningful output is addressable, inspectable, and reusable

4. **Separation of concerns**
   - Import ≠ Processing ≠ Output Sync

5. **UI explains outcomes, not implementation**
   - Users reason about assets, results, and comparisons—not jobs and queues

---

## Core Storage & Consistency Principles

To ensure Curatore remains scalable, understandable, and cost‑efficient, the following principles govern how the database, object store, and jobs interact.

### Database as Source of Truth
- The relational database is the authoritative source of meaning and ownership.
- The object store contains only bytes and has no semantic authority.
- Any object in the object store without a database reference is considered orphaned and eligible for cleanup.
- No database record may reference an object store path it does not explicitly own.

### Strict Object Store Layout
All objects must live under a small, fixed set of prefixes that map directly to database concepts:

- `raw/asset/{asset_id}/` — immutable original content
- `extracted/asset/{asset_id}/v{extractor_version}/` — canonical extracted content
- `runs/run/{run_id}/artifacts/` — derived outputs from processing runs
- `experiments/experiment/{experiment_id}/variants/` — exploratory LLM outputs
- `exports/sync/{sync_id}/` — externally published payloads

Ad‑hoc or user‑defined paths are not permitted.

### Derived Data Is Rebuildable
- Only raw assets are treated as non‑replaceable.
- All extracted, processed, and synchronized objects must be reproducible from inputs, configuration, and code version.
- Loss of derived objects must not corrupt system state; regeneration is always possible.

---

## Current Architecture (Baseline)

Curatore today already provides strong foundations:

- **Frontend**
  - Asset-centric navigation
  - Batch/job progress monitoring
  - Connection configuration

- **Backend**
  - FastAPI-based API
  - Async job execution (Celery-style workers)
  - Per-org concurrency controls
  - Cancellation and retention logic

- **Object Store**
  - Durable storage for uploaded files and generated outputs
  - Primary system of record for content artifacts

- **Connection System**
  - External integrations (LLM providers, vector DBs, Open WebUI, etc.)
  - Runtime-configurable credentials and endpoints

This proposal **extends** these capabilities without invalidating them.

---

## Curatore Data Lifecycle (Proposed)

Curatore should explicitly model four phases:

```
Import / Ingest
      ↓
Canonicalization (Automatic Extraction)
      ↓
Processing & Experimentation
      ↓
Output Synchronization
```

These phases are **not all jobs**. Some are platform behaviors.

---

## 1. Import / Ingest

### Purpose
Introduce raw data into Curatore with full provenance.

### Examples
- File uploads
- Web scraping (crawl runs)
- API-based imports
- External repository syncs

### Key Characteristics
- Creates an **Asset**
- Stores immutable raw bytes
- Records source metadata (URL, timestamp, crawl run, uploader)
- Can be synchronous or asynchronous

### Data Model (Conceptual)
- Asset
  - id
  - source_type
  - source_metadata
  - raw_object_ref
  - created_at

---

## 2. Canonicalization (Automatic Extraction)

### Purpose
Ensure every asset has a **standard, reliable representation** for downstream processing.

### Key Rules
- Triggered automatically on asset creation or version change
- No per-workflow configuration
- Idempotent and versioned
- Failures are visible but non-blocking

### Typical Outputs
- Extracted text (markdown or structured text)
- Page or section boundaries
- Basic structural metadata
- OCR results where applicable

### Data Model
- ExtractionResult
  - asset_id
  - extractor_version
  - status
  - extracted_content_ref
  - structure_metadata
  - warnings / errors

### Why This Matters
- All experiments start from the same baseline
- Eliminates “why did this extract differently?”
- Simplifies mental model and UI

### Object Store Guarantees
- Each asset has at most one canonical extraction per extractor version.
- Extraction outputs are never job‑specific or workflow‑specific.
- Downstream processing always operates on the canonical extracted content unless explicitly overridden by system policy.

Extraction is **not a job step**. It is a **platform guarantee**.

---

## Flexible Document Metadata Model


## Scheduling, Daemons, and System Maintenance

Curatore’s current stack (FastAPI + Celery workers + Redis) is sufficient to implement recurring and maintenance activities **natively**. The key is to avoid ad-hoc “cron scripts” and instead standardize on a single concept:

> **Scheduling creates Runs; Runs own execution, logging, and outputs.**

This keeps scheduled activity visible, auditable, and consistent with user-triggered processing.

### What Must Be Scheduled
Typical scheduled / daemon-like activities include:
- Automatic extraction backfills / re-extraction when extractor versions change
- Retention enforcement and garbage collection (object store + DB-level cleanup)
- Orphan detection (object store objects without DB references)
- Periodic re-scraping / crawl revisits
- Health checks / queue hygiene (optional)

### Minimal Scheduling Data Model (Native)

Curatore should introduce a minimal, DB-backed scheduling model. This is intentionally small to preserve development speed and avoid workflow-engine complexity.

#### ScheduledTask (Intent Record)
A `ScheduledTask` defines **what** should run and **when**; it does not perform execution itself.

Suggested fields:
- `id`
- `organization_id` (nullable for global tasks)
- `name`
- `task_type` (e.g. `gc.cleanup`, `scrape.revisit`, `extract.rebuild`)
- `scope_type` (`organization` | `collection` | `global`)
- `scope_id` (nullable; null = global)
- `schedule_type` (`interval` | `cron`)
- `schedule_expression` (e.g. cron `0 3 * * *` or ISO-8601 duration `P7D`)
- `enabled` (bool)
- `config` (JSON; task-specific)
- `created_at`, `updated_at`
- `last_run_at` (nullable)

**Note:** Organizations remain the primary isolation boundary; scheduled tasks must run within a single org context (or explicitly global).

#### SystemRun (Optional Convenience)
Curatore may optionally introduce a `SystemRun` link table to clearly separate system-triggered runs from user-triggered runs without changing the primary run UX.

Suggested fields:
- `id`
- `scheduled_task_id`
- `run_id`
- `triggered_at`
- `status`
- `summary` (JSON)

If desired, this can be collapsed into `Run.origin = user|system` with a `scheduled_task_id` nullable FK.

### Scheduler Execution Pattern

A lightweight scheduler loop (Celery beat or an equivalent periodic trigger) should:
1. Query enabled `ScheduledTask` rows that are due
2. Create a `Run` (origin=`system`) in the correct org/scope context
3. Enqueue a worker task by `run_id`
4. Update `ScheduledTask.last_run_at`

The scheduler must remain dumb: it only creates runs and enqueues work.

### Idempotency and Concurrency

- Scheduled tasks must be idempotent by design.
- The scheduler should avoid double-enqueue by acquiring a lightweight distributed lock per `ScheduledTask` (e.g., Redis lock) or by atomically updating a “claimed” state in DB.
- Runs inherit existing org-level concurrency limits to prevent maintenance tasks from starving user workloads.

As Curatore matures, documents will accumulate increasing amounts of derived metadata (topics, summaries, tags, entities, scores, classifications, etc.). The system must support this growth **without requiring frequent schema migrations or a monolithic “big table.”**

### Core Principles
- Metadata is **additive and evolvable**
- Metadata is **not all equal** (some is canonical, some experimental)
- Metadata is **queryable, inspectable, and attributable**
- Metadata creation should reuse the same run/experiment framework as other processing

---

### Metadata as First-Class Artifacts

All derived metadata is stored as **metadata artifacts**, not hard-coded columns.

Each metadata artifact:
- Is associated with one asset
- Has a declared `metadata_type`
- Has a producing run (or system extractor)
- Has a schema version
- Is stored as a structured object (JSON or similar)

Example metadata types:
- `topics.v1`
- `summary.short.v1`
- `summary.long.v1`
- `tags.llm.v1`
- `entities.gov_contract.v1`

This allows new metadata types to be introduced without database schema changes.

---

### Data Model (Conceptual)

- AssetMetadata
  - id
  - asset_id
  - metadata_type
  - schema_version
  - producer_run_id (nullable for system-generated metadata)
  - metadata_object_ref
  - created_at
  - status (active | superseded | deprecated)

The actual metadata payload lives in the object store and is referenced, not inlined.

---

### Canonical vs Experimental Metadata

Not all metadata should be treated equally.

- **Canonical metadata**
  - Stable
  - Single active version per asset
  - Used by default in UI and downstream processing
  - Examples: primary summary, core topics, normalized tags

- **Experimental metadata**
  - Multiple variants allowed
  - Produced by experiment runs
  - Used for comparison and evaluation
  - Must be explicitly promoted to canonical

Promotion is a metadata-level action, not a reprocessing of the asset.

---

### UI Implications

The document view should present metadata in layers:

- **Canonical Metadata**
  - Always visible
  - Clearly labeled and trusted

- **Experimental / Alternate Metadata**
  - Viewable on demand
  - Attributed to specific runs/configs
  - Comparable side-by-side

Users never edit metadata objects directly; they promote, demote, or regenerate them via runs.

---

### Query & Search Strategy

- Frequently queried metadata (e.g., canonical tags, topics) may be indexed into dedicated search tables or search infrastructure.
- Less common or experimental metadata remains object-backed.
- This enables performance optimization without sacrificing flexibility.

---

### Why This Works

- No schema churn as metadata evolves
- Clear provenance and auditability
- Supports experimentation without polluting the canonical view
- Aligns metadata creation with Curatore’s run and artifact model


## 3. Processing & Experimentation

### Purpose
Allow users to explore, test, and refine transformations and synthesis logic.

This is where Curatore differentiates itself.

### Core Concept: Runs

A **Run** represents executing logic against extracted content.

Runs can be:
- Experiments (exploratory, comparative)
- Repeatable processes
- Automated pipelines (later)

### Run Characteristics
- Operates on extracted content by default
- Produces one or more artifacts
- Fully observable and repeatable
- Cheap to create and discard

### Example Run Types
- Past Performance synthesis
- Chunking strategy comparison
- Embedding model evaluation
- Classification or tagging
- Summarization

### Experiment Mode (Critical)

For LLM-based work, Curatore must support **experiment runs**:

- Same inputs
- Multiple configs (prompt, model, schema)
- Side-by-side outputs
- Metrics (tokens, cost, completeness)
- Human review and selection

No pipeline definitions required.

-### Data Model
- Run
  - id
  - run_type
  - input_asset_ids
  - config
  - status
  - started_at / completed_at


### Run Logging & Progress Conventions

Curatore must standardize logging and progress reporting so that the UI can remain simple and consistent as job types expand.

#### Core Rule: Everything Important Has a Run ID
Any background activity that matters (user runs, system extraction, maintenance, sync) must be attributable to a `run_id`. If it cannot be traced to a run, it is not observable.

#### Run Status Transitions (Strict)
Runs may transition only:
- `pending → running → completed`
- `pending → running → failed`
- `pending → running → cancelled`

Status transitions should be atomic and should emit a corresponding log event.

#### Minimal Progress Contract (UI-Friendly)
Long-running runs must periodically update progress in a consistent shape so the frontend can render reliable progress bars and summaries:

- `progress.current` (int)
- `progress.total` (int, nullable if unknown)
- `progress.unit` (string, e.g., `documents`, `pages`, `urls`)
- `progress.percent` (0–100, optional but recommended)

Progress should be stored in `Run.progress` (JSON) and may optionally emit progress log events for timeline views.

#### Structured Run Events (DB-Backed)
Store **events**, not verbose raw logs, in the database.

Suggested `RunLogEvent` fields:
- `id`
- `run_id`
- `level` (`INFO` | `WARN` | `ERROR`)
- `event_type` (`start` | `progress` | `retry` | `error` | `summary`)
- `message` (human-readable)
- `context` (JSON; machine-readable details)
- `created_at`

This powers:
- frontend timelines
- error summaries
- operational audits

#### Full Logs (Object Store)
Verbose logs (stack traces, large payload details) should not bloat the DB:
- Stream full logs to an object store file
- Store only a `log_object_ref` on `Run` (optional)
- UI shows structured events by default with an optional link to full logs

#### Failure Convention
On failure:
1. Set `Run.status = failed`
2. Emit a `RunLogEvent` with `level=ERROR` and a concise human summary
3. Attach diagnostic artifacts only when useful (e.g., a JSON error report)

Avoid storing raw stack traces in DB fields; keep them in object-store-backed logs.

#### Maintenance / Cleanup Summary Convention
Maintenance runs (GC, orphan cleanup, retention enforcement) should always emit a `summary` event with counts, for example:
- `deleted_objects`
- `skipped_objects`
- `orphaned_objects_detected`
- `errors`

This makes nightly activity easy to understand from the UI without reading logs.

- RunArtifact
  - run_id
  - artifact_type
  - artifact_ref
  - metrics
  - created_at

---

## 4. Output Synchronization

### Purpose
Publish selected artifacts to downstream systems.

### Characteristics
- Decoupled from processing
- Asynchronous and repeatable
- Auditable
- Optional

### Examples
- Load embeddings into vector DB
- Publish dataset to Open WebUI collection
- Export dataset (Parquet/CSV)
- Send notifications or webhooks

### Implementation
Initially implemented as **explicit sync actions**, not full pipelines.

Later, sync actions may be attached to automated runs.

---

## Web Scraping as a First-Class Domain

Web scraping is expected to be:
- The largest data source
- Long-running and incremental
- Frequently revisited

### Recommended Model
- ScrapeCollection
- CrawlRun
- PageAsset (per URL snapshot)
- ExtractionResult (per page)

Scraping produces **assets**, which flow naturally into the same extraction and processing lifecycle as uploaded files.

---

## Organizational & Security Model

Curatore enforces a logical organizational hierarchy that governs visibility, access control, and resource isolation.

### Organizational Structure
- Organization
  - Users
  - Connections
  - Asset Collections
  - Scrape Collections
  - Runs and Experiments
  - Output Sync Targets

All assets, runs, and artifacts are owned by exactly one organization.

### Collections as the Primary Grouping Mechanism
- Assets belong to one or more collections.
- Collections are the primary unit for:
  - Job input selection
  - Access control
  - Retention policies
  - Scraping scope
- Users interact with collections, not raw files.

### Security Boundaries
- Organizations are hard isolation boundaries.
- Object store paths are namespaced by organization.
- Cross‑organization access is never permitted.
- Connections are scoped to an organization and explicitly attached to runs or sync actions.

### Job and Run Scoping
- Runs execute within a single organization context.
- Runs may reference only assets and collections owned by that organization.
- Output synchronization is constrained to connections owned by the same organization.

This model ensures clarity, safety, and predictability as Curatore scales to large datasets and multiple tenants.

---

## UI / UX Implications

The frontend experience must reflect Curatore’s core philosophy: **users interact with documents, understanding, and outcomes—not jobs, workflows, or storage mechanics**. The backend absorbs complexity so the UI can remain intuitive, powerful, and extensible.

This section defines the canonical user experience Curatore’s architecture must support.

---

### Primary User Mental Model

From a user’s perspective, Curatore consists of:

- **Collections** — logical groupings of documents (uploaded, synced, or scraped)
- **Documents** — individual files or pages Curatore understands
- **Understanding** — extracted content and metadata
- **History & Experiments** — how understanding was produced and refined
- **Outputs** — where curated data is published

Jobs, runs, extraction processes, and scheduling are implementation details and should never be primary UI concepts.

---

### File Upload & Batch Processing Experience

When users upload files (single or folder-based):

- Files immediately appear in the target collection
- Backend automatically creates a batch run
- Automatic extraction is triggered per asset
- UI displays status badges:
  - `Uploading`
  - `Processing`
  - `Ready`
  - `Needs Attention`

Uploading files must feel like **adding documents**, not starting jobs.

#### Automatic Update Detection (Manual Uploads)

When uploading files into an existing collection, Curatore should support **bulk update recognition**:

- Files are matched using filename/path + content fingerprint
- Upload analysis categorizes files as:
  - Unchanged
  - Updated
  - New
  - Missing (optional, non-destructive)

Users are presented with a single confirmation step to apply updates in bulk.

Updated files:
- Create a new asset version
- Trigger automatic re-extraction
- Preserve historical versions and runs

Missing files are never deleted automatically; they may be marked inactive.

---

### Collection Browsing Experience

Collections are the primary navigation unit.

Each collection displays:
- Name
- Source type (Upload | SharePoint | Web Scrape)
- Document count
- Last updated timestamp
- Health indicator

Clicking a collection reveals a document list, never raw storage paths.

---

### Document List View

Each document row shows:

**Always visible**
- Document name/title
- Source icon
- Processing status
- Last extraction timestamp
- Canonical tags/labels
- Short canonical summary (1–2 lines)

**On hover or expansion**
- Source details (uploaded by, SharePoint path, URL)
- Last run summary
- Warnings or extraction issues

This view must remain stable as metadata types evolve.

---

### Document Detail View (Core Interaction Surface)

Each document has a consistent detail view regardless of source.

Recommended tabs:

#### Original
- View or download original content
- Source provenance
- Read-only

#### Extracted Content
- Rendered extracted markdown
- Page/section navigation
- Extraction timestamp and version
- Action: **Re-run extraction**

#### Metadata
Displayed in two layers:

- **Canonical Metadata**
  - Summary
  - Topics
  - Tags
  - Key entities
  - Always visible and trusted

- **Experimental Metadata**
  - Collapsible
  - Attributed to specific runs/configurations
  - Comparable side-by-side
  - Explicitly promoted to canonical when chosen

#### History & Runs
- Timeline of runs affecting the document
- Extraction, experiments, syncs
- Human-readable summaries
- No raw logs by default

---

### Source-Specific Affordances (Unified UX)

All documents share the same core UI. Source differences affect **available actions**, not layout.

#### Manually Uploaded Files
- Upload additional files
- Replace/update via folder re-upload
- Re-run extraction
- Delete asset (with safeguards)

#### SharePoint-Synced Collections
- View sync status
- Trigger re-sync
- View source path
- Upload/replace disabled

#### Web-Scraped Collections
- View source URL
- View crawl history
- Trigger re-crawl
- Upload/replace disabled

---

### Web Scraping: Change Over Time & Record Preservation

Web scraping must support both **site monitoring** and **institutional memory creation**.

#### Pages vs Records (Critical Distinction)

- **Pages** are ephemeral discovery assets:
  - Listings, indexes, navigation pages
  - May change, move, or disappear
  - Versioned and GC-eligible

- **Records** are durable captured assets:
  - RFPs, RFIs, notices, attachments
  - Once discovered, never auto-deleted
  - Identity derived from stable identifiers, not URLs

Scraped pages act as discovery mechanisms; records become first-class assets.

#### Web Scrape Collection Modes

Curatore must support two behavioral modes for scraped collections:

1. **Snapshot / Monitoring Mode**
   - Focus on current site state
   - Pages are primary assets
   - Limited retention acceptable

2. **Record-Preserving Mode**
   - Focus on capturing durable records
   - Records promoted to permanent assets
   - Page disappearance never deletes records

This distinction is architectural and behavioral; the UI remains unified.

---

### Website Hierarchy & Crawl Scope

Web-scraped collections must project a **hierarchical structure** analogous to directories.

- Tree-based browsing by URL path
- Collapsible sections
- Search across pages and records

Crawl depth is abstracted as **scope**:
- Root URL
- Path-based inclusion
- Optional advanced limits (depth, page count)

Numeric crawl depth is not a primary UI concept.

---

### Re-Crawling & Refresh Semantics

Users may:
- Re-crawl entire collections
- Re-crawl specific subtrees
- Refresh changed pages only (future)

Re-crawls:
- Produce new page versions
- Never delete existing record assets
- Are fully traceable via runs

---

### Connections & External Sources

Connections are managed centrally per organization.

- Configured once
- Tested independently
- Referenced by collections

Document views never expose credentials or connection internals.

---

### Frontend / Backend Responsibility Boundary

**Backend**
- Extraction
- Runs & scheduling
- Metadata versioning
- Sync logic
- Retention & cleanup

**Frontend**
- Presentation
- Safe user actions
- Comparison and promotion flows
- Trust, clarity, and discoverability

APIs must return fully-resolved, meaningful objects (documents with canonical understanding), never raw artifacts.

---

### UX Guardrails

The UI must never expose:
- Object store paths
- Extractor internals
- Scheduling mechanics
- Raw logs by default
- Metadata schema versions

If these appear, complexity has leaked.

---

### Architectural Implications

To support this UX, the backend must natively support:
- Asset versioning
- Canonical vs experimental metadata
- Record-preserving scrape semantics
- Hierarchical scrape metadata
- Bulk update detection on upload
- Run-based observability for all background activity

These are foundational requirements, even if some features are implemented incrementally.

## Phased Implementation Plan

### Phase 1 — Extraction as Infrastructure
- Automatic extraction on asset ingest
- ExtractionResult persistence
- UI surface for extracted content

### Phase 2 — Run & Artifact Core
- Introduce Run and RunArtifact models
- Simple processing runs
- Artifact browsing and inspection

### Phase 3 — Experimentation UX
- Multi-config experiment runs
- Comparison views
- Metrics and evaluation support

### Phase 4 — Output Sync
- Vector DB and Open WebUI sync actions
- Repeatable, auditable publishing

### Phase 5 — Automation
- Optional chaining of runs
- Limited pipelines for stabilized workflows

---

## Key Guardrails

- Do not expose extraction configuration prematurely
- Do not require pipelines for experimentation
- Do not overload the UI with workflow concepts
- Optimize for clarity, iteration speed, and trust

---

## Conclusion

This architecture positions Curatore as a **curation and experimentation platform first**, with automation as an emergent capability rather than a prerequisite.

By treating extraction as infrastructure, separating concerns cleanly, and designing for rapid LLM iteration, Curatore can scale in capability without sacrificing usability or velocity.

The result is a system that supports today’s needs while remaining flexible enough for tomorrow’s pipelines.
