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

### Large & Structured Document Handling (Hierarchical Extraction)

Certain documents ingested into Curatore are **structurally complex and extremely large** (e.g., regulatory compendiums such as the Federal Acquisition Regulation, multi‑thousand‑page policy manuals, standards documents, or encyclopedic references).

These documents must be handled **automatically** without requiring users to select a special workflow, job type, or extraction mode.

#### Core Principle

> **Document size or structural complexity must never require user intervention.  
> Extraction strategy selection is a platform responsibility.**

Large-document handling is an **extension of canonical extraction infrastructure**, not a separate workflow.

---

#### Extraction Strategy Selection

During canonical extraction, the extractor inspects the asset to determine an appropriate strategy based on:
- File size and page count
- Structural signals (table of contents, headings, numbering)
- Content type (text-based PDF, scanned PDF, mixed)

Possible strategies include:
- Simple extraction (single-unit output)
- OCR-assisted extraction
- Hierarchical extraction (multi-unit structured output)

This decision is internal and invisible to the user.

---

#### Hierarchical Extraction Model

For large structured documents, extraction produces a **hierarchical set of extracted units** rather than a single monolithic output.

Key characteristics:
- One raw asset
- One `ExtractionResult`
- Many extracted units, organized in a tree
- Stable, deterministic unit identifiers
- Addressable units for downstream processing

#### Extraction Manifest

Hierarchical extraction emits an **extraction manifest** describing the structure and outputs.

Conceptual example:

```json
{
  "manifest_type": "hierarchical",
  "units": [
    {
      "unit_id": "part_15",
      "title": "Part 15 — Contracting by Negotiation",
      "path": ["Part 15"],
      "content_ref": "extracted/asset/{asset_id}/v{version}/part_15.md",
      "children": [
        {
          "unit_id": "15.404",
          "title": "15.404 Proposal Analysis",
          "path": ["Part 15", "15.404"],
          "content_ref": "extracted/asset/{asset_id}/v{version}/15.404.md"
        }
      ]
    }
  ]
}
```

The manifest itself is stored as an object-store artifact and referenced by the `ExtractionResult`.

---

#### Extended ExtractionResult (Conceptual)

```
ExtractionResult
- asset_id
- extractor_version
- status
- extraction_manifest_ref
- warnings / errors
- created_at
```

For non-hierarchical documents, the manifest contains a single root unit.

---

#### Downstream Processing & Search

All downstream systems operate on **extracted units**, not raw pages:

- Runs may target:
  - Entire assets
  - Specific extracted units
  - Subtrees within the hierarchy
- Deterministic filtering, keyword search, and semantic search operate at the unit level
- Vector synchronization (if used) indexes extracted units, never raw blobs

This enables:
- Precise retrieval
- Efficient LLM context usage
- Scalable processing of very large documents

---

#### Metadata & Summaries for Large Documents

Metadata may be produced at multiple levels:
- Unit-level metadata (e.g., section summaries, tags)
- Intermediate node metadata (e.g., Part-level summaries)
- Document-level metadata (derived aggregations)

All metadata follows standard `AssetMetadata` rules and is fully attributable to producing runs.

---

#### UI / UX Implications

From the user’s perspective:
- Large documents appear as **browsable structured documents**
- Navigation is tree-based (parts, sections, subsections)
- Extracted content is viewed per unit
- Search is scoped to the document by default
- No chunking, extraction strategy, or job selection is exposed

Small documents continue to appear and behave exactly as they do today.

---

#### Backward Compatibility Guarantee

- Manual uploads continue to trigger automatic extraction without configuration
- Existing documents extracted as single units remain valid
- Hierarchical extraction is additive and does not invalidate prior behavior
- No existing APIs or workflows are removed or redefined

This extension ensures Curatore can handle both everyday documents and extremely large reference corpora with a unified, intuitive user experience.

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


### In-Run Search & Ephemeral Semantic Computation

### Search Access Model (Engineer Guidance)

```
Curatore exposes search as a run-scoped capability, not as a standalone platform service.

All search and retrieval is accessed through a single, unified run-level interface that progressively applies increasingly expensive techniques as needed. Runs do not directly select or configure specific search backends.

Search escalation follows this order:

1. Deterministic filtering (always applied)
   - Relational queries over assets, domain models, and canonical metadata
   - Used to constrain scope by time, collection, status, or priority
   - Requires no external services or connections

2. Keyword / full-text search (automatic when applicable)
   - Applied to canonical extracted content only
   - Used to narrow candidate sets before further processing
   - Implemented via database full-text search or in-process text scanning

3. Ephemeral semantic search (run-scoped, optional)
   - In-memory chunking, embedding generation, and similarity comparison
   - Uses existing LLM embedding connections
   - Embeddings are not persisted and are discarded when the run completes

4. Persistent semantic search (optional, downstream)
   - Implemented only via explicit output synchronization to a vector database
   - Used for interactive or large-scale semantic retrieval
   - Vector indexes are rebuildable and never treated as sources of truth

Configuration principles:
- Search behavior is owned by platform code, not user configuration
- Runs may request semantic search, but never select infrastructure details
- Users never configure search modes, thresholds, or models
- Absence of a connection (e.g., vector DB or embeddings) gracefully disables that capability
```

Runs may perform transient search and retrieval operations over extracted content as part of processing or experimentation.

This includes:
- Deterministic filtering using relational data and canonical metadata
- Keyword or full-text search over canonical extracted content
- Ephemeral chunking, embedding generation, and similarity comparison executed in-memory during a run

Ephemeral search and embeddings:
- Are scoped to the lifetime of a single run
- Are not persisted as system state
- Do not create canonical metadata unless explicitly emitted as artifacts
- Must be fully reproducible from inputs, configuration, and code

Curatore does not require a persistent semantic index to support summaries, reports, or notifications. Persistent vector indexes, when needed, are implemented exclusively as output synchronization targets and must be fully rebuildable from canonical extracted content.

---


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

### Notifications & Messaging Outputs

Email notifications, messaging, and webhook deliveries are treated as output synchronization actions.

Notifications:
- Consume existing canonical understanding and run artifacts
- Produce rendered message artifacts attributable to a run
- Must not create or mutate canonical metadata
- Are observational outputs, not generators of system understanding

Notification jobs are implemented as system or user-triggered runs and are fully observable through standard run status, events, and artifacts.

---

## Web Scraping as a First-Class Domain


## Structured Domain Ingestion: SAM.gov Opportunities

### Overview

SAM.gov ingestion represents a **structured domain ingestion pipeline** rather than simple document scraping. The SAM.gov API provides time-versioned, relational records (Solicitations and Notices) alongside unstructured supporting artifacts (attachments and linked documents). Curatore must treat this data as **durable business records** designed for reuse across multiple workflows and outputs.

The SAM.gov pipeline must:
- Preserve full historical fidelity
- Separate structured domain records from unstructured assets
- Enable downstream experimentation and reporting without re-ingestion
- Align with Curatore’s asset, run, and metadata principles

---

### Domain Data Model (Conceptual)

#### Solicitation (Relational, Long-Lived)
Represents the long-lived procurement opportunity lifecycle.

Fields (indicative):
- `id`
- `organization_id`
- `sam_solicitation_number`
- `title`
- `agency_path_name`
- `agency_path_code`
- `naics_codes` (array)
- `classification_code`
- `set_aside_type`
- `status` (open | archived | awarded | cancelled)
- `open_date`
- `close_date`
- `archive_date`
- `created_at`
- `updated_at`

#### Notice (Relational, Time-Versioned)
Represents individual SAM.gov notices tied to a solicitation.

Fields (indicative):
- `id`
- `solicitation_id` (FK)
- `sam_notice_id`
- `notice_type` (e.g. Solicitation, Award Notice, Special Notice)
- `posted_date`
- `response_deadline`
- `active`
- `raw_payload_ref`
- `created_at`

Each notice must preserve its full raw JSON payload as an immutable artifact in the object store.

---

### Unstructured Artifacts (Assets)

Attachments and linked documents referenced by notices are ingested as standard Curatore assets:
- Stored in the object store under `raw/asset/{asset_id}/`
- Automatically extracted via canonical extraction
- Linked to the originating notice via relational association

These assets may be reused across multiple runs, experiments, reports, and output syncs.

---

### Raw Payload Preservation

All SAM.gov API responses must be preserved in the object store:
- Raw notice JSON payloads
- Description endpoints (HTML/text)
- Attachment metadata

The database stores references, not inline payloads. This guarantees lossless ingestion and supports future reprocessing as requirements evolve.

---

### Ingestion & Execution Model

SAM.gov ingestion is executed as a **scheduled system run**:

- A `ScheduledTask` (e.g. `sam.daily_ingest`) triggers a system-originated `Run`
- The run performs:
  1. API fetch and pagination
  2. Normalization into Solicitation and Notice records
  3. Asset creation for attachments
  4. Automatic extraction for new assets
  5. Optional downstream processing (e.g. prioritization, summarization)

Downstream processing must depend on extraction completion but does not require workflow orchestration. Runs query system state to determine readiness.

---

### Prioritization & Derived Intelligence

Priority signals (e.g. NAICS matching, agency filters) are treated as **derived metadata**, not schema fields.

- Stored as `AssetMetadata` or `NoticeMetadata`
- Produced by runs
- Promotable to canonical status
- Comparable across experiments

Executive summaries and daily reports are produced as run artifacts and may be synchronized externally.

---

### Multi-Use & Synchronization

SAM.gov data is ingested once and reused many times.

- SharePoint synchronization is an output sync referencing existing assets
- No duplicate ingestion or re-scraping is permitted for downstream needs
- Vectorization and RAG preparation operate on canonical extracted content

This ensures consistency and avoids data divergence.

---

### UI / UX Implications

SAM.gov collections are presented as **specialized record collections**:
- Primary view: Solicitation list
- Drill-down: Notices, attachments, extracted content, summaries
- Users never interact with raw JSON or storage paths
- Runs, extraction, and scheduling remain background concepts

---

### Architectural Requirements

To support SAM.gov ingestion natively, Curatore must provide:
- Relational domain models alongside assets
- Run-attributed structured ingestion
- Raw payload artifact preservation
- Attachment-to-record linking
- Metadata extensibility without schema churn

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

This phased plan is designed to:
- Preserve existing functionality at every step
- Introduce foundational capabilities before feature surface area
- Coordinate backend and frontend changes tightly to maintain debuggability
- Explicitly separate **required foundations** from **optional / future integrations**

Each phase should result in a system that is:
- Deployable
- Observable
- Usable by real users
- Easier to reason about than before

---

### Phase 0 — Stabilization & Baseline Observability (Immediate)

**Goal:** Make existing behavior explicit, traceable, and safe to evolve.

**Backend**
- Normalize the concept of `Asset`, `Run`, and `ExtractionResult` in code
- Ensure every upload triggers:
  - Asset creation
  - Automatic extraction
  - A system `Run` with logs and progress
- Enforce DB-as-source-of-truth for object store references
- Introduce structured run logging (`RunLogEvent`)
- Ensure extraction failures are visible but non-blocking

**Frontend**
- Surface extraction status consistently (`Uploading`, `Processing`, `Ready`, `Needs Attention`)
- Add basic run visibility (read-only timeline per document)
- Clearly distinguish raw file vs extracted content in the UI

**Why this phase matters**
Without this baseline, later changes are difficult to debug and trust.

---

### Phase 1 — Asset-Centric UX & Versioning Foundations

**Goal:** Make documents feel stable, inspectable, and version-aware.

**Backend**
- Introduce asset versioning (immutable raw versions)
- Support re-extraction on version change
- Store extraction metadata (timestamps, extractor version)
- Support manual re-run extraction as a system run
- Lay groundwork for bulk upload diffing (fingerprints, paths)

**Frontend**
- Introduce a consistent Document Detail View:
  - Original
  - Extracted Content
  - Metadata (canonical-only at first)
  - History
- Expose “Re-run extraction” safely
- Show asset update history (non-destructive)

**Why this phase matters**
This is the foundation for user trust and later experimentation.

---

### Phase 2 — Bulk Upload Updates & Collection Health

**Goal:** Eliminate friction for real-world document updates.

**Backend**
- Implement bulk upload analysis:
  - unchanged / updated / new / missing
- Create new asset versions for updates
- Trigger automatic re-extraction for updated assets
- Track collection-level health signals

**Frontend**
- Folder re-upload UX with single confirmation step
- Clear preview of detected changes (counts, not per-file clicks)
- Collection-level health indicators
- Non-destructive handling of missing files

**Why this phase matters**
This is where Curatore becomes usable at scale, not just for demos.

---

### Phase 3 — Flexible Metadata & Experimentation Core

**Goal:** Enable LLM-driven iteration without schema churn or backend scripts.

**Backend**
- Implement `AssetMetadata` as first-class artifacts
- Support canonical vs experimental metadata
- Enable experiment runs that produce metadata variants
- Add promotion/demotion mechanics (pointer updates, not recompute)
- Ensure all metadata-producing activity is run-attributed

**Frontend**
- Metadata tab with:
  - Canonical metadata (default)
  - Experimental metadata (collapsible)
- Side-by-side comparison for experiment outputs
- Explicit “Promote to Canonical” actions
- Clear attribution to runs/configs

**Why this phase matters**
This unlocks Curatore’s differentiation without committing to automation.

---

### Phase 4 — Web Scraping as a Durable Data Source

**Goal:** Treat web scraping as institutional memory, not transient crawling.

**Backend**
- Introduce scrape collections with:
  - Discovery (page) assets
  - Durable record assets
- Support hierarchical path metadata
- Ensure record-preserving behavior (no auto-deletes)
- Implement crawl runs and re-crawl semantics
- Integrate scheduled re-crawls via `ScheduledTask`

**Frontend**
- Tree-based browsing for scraped collections
- Clear distinction between pages and captured records
- Crawl history and status visibility
- Re-crawl actions at collection and subtree levels

**Why this phase matters**
This prevents irreversible data loss and supports high-value use cases (e.g., SAM.gov).

---

### Phase 5 — System Maintenance & Scheduling Maturity

**Goal:** Make the system self-maintaining and operable long-term.

**Backend**
- Implement `ScheduledTask` and scheduler loop
- Add maintenance runs:
  - GC
  - orphan detection
  - retention enforcement
- Enforce idempotency and locking
- Add summary reporting for system runs

**Frontend**
- Admin/system views for scheduled activity (read-only initially)
- Visibility into maintenance outcomes (summaries, not logs)
- Clear separation of user vs system activity

**Why this phase matters**
This phase reduces operational risk and supports confident scaling.

---

### Phase 6 — Optional Integrations & Automation (Explicitly Non-Blocking)

**Goal:** Extend Curatore outward without destabilizing the core.

**Backend (Optional / TODO)**
- Vector DB sync actions
- OpenWebUI publication
- External notifications/webhooks
- Limited automation chaining for stabilized workflows

**Frontend (Optional / TODO)**
- Output destination configuration
- Sync history and status views
- Automation opt-in controls

**Important**
These integrations are **not required** for Curatore’s core value and must not block earlier phases.

---

### Phase 7 — Native SAM.gov Domain Integration (Future)

**Goal:** Migrate SAM.gov ingestion from scripts into Curatore as a first-class domain pipeline.

**Backend**
- Introduce Solicitation and Notice relational models
- Implement SAM.gov API abstraction layer
- Convert daily ingest script into a scheduled system run
- Integrate attachment ingestion with asset + extraction pipeline
- Enable derived metadata and reporting runs

**Frontend**
- Add SAM.gov collection type
- Solicitation-centric browsing and filtering
- Notice history and attachment visibility
- Executive report access and export

**Why this phase matters**
This phase transforms ad-hoc ingestion into a durable, reusable intelligence capability without overfitting the core platform.

## Phase Coordination & Debuggability Principles

Across all phases:
- Backend changes must land with at least minimal UI visibility
- Frontend features must rely on stable, documented API contracts
- Every background activity must be traceable to a Run
- No phase should introduce opaque behavior

Progress should be tracked by:
- Reduction in “invisible work”
- Fewer ad-hoc scripts
- Increased confidence in system state

This phased approach prioritizes correctness, clarity, and user trust over feature count.

---

### Search, Summarization, and Notification Implementation by Phase

The following guidance clarifies when search, summarization, and notification capabilities should be introduced:

- Phase 0–1:
  - Relational filtering and deterministic queries only
  - No semantic search or embeddings
  - No notifications

- Phase 2:
  - Optional lightweight keyword or full-text search over canonical extracted content
  - Search used only to narrow candidate sets for runs

- Phase 3:
  - Ephemeral in-run semantic search (chunking, embeddings, similarity)
  - LLM-based summarization and aggregation within runs
  - No persistent semantic indexes

- Phase 5:
  - Scheduled notification and summary runs (email, webhook)
  - Notifications implemented as output synchronization actions

- Phase 6 (Optional):
  - Persistent vector database synchronization for interactive or large-scale semantic retrieval
  - Vector indexes treated as rebuildable downstream systems, never sources of truth
