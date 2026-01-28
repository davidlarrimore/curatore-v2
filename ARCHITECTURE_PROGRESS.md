# Curatore v2 Architecture Refactor Progress

> **Full Requirements**: See `/UPDATED_DATA_ARCHITECTURE.md` (1400+ lines)
> **Start Date**: 2026-01-28
> **Current Phase**: Phase 0 - Stabilization & Baseline Observability

---

## Quick Reference: Core Architectural Principles

1. **Extraction is infrastructure** - Automatic, opinionated, consistent (not per-workflow)
2. **Experimentation precedes automation** - Test/compare/iterate before pipelines
3. **Artifacts are first-class** - Every output is addressable, inspectable, reusable
4. **Separation of concerns** - Import ≠ Processing ≠ Output Sync
5. **UI explains outcomes, not implementation** - Users see assets/results, not jobs/queues

### Storage & Consistency Rules
- **Database is source of truth** - Object store contains only bytes
- **Strict object store layout** - Fixed prefixes only (raw/, extracted/, runs/, experiments/, exports/)
- **Derived data is rebuildable** - Only raw assets are non-replaceable

### Core Data Lifecycle
```
Import/Ingest → Canonicalization (Auto Extraction) → Processing & Experimentation → Output Sync
```

---

## Phase 0: Stabilization & Baseline Observability 🔄 IN PROGRESS

**Goal**: Make existing behavior explicit, traceable, and safe to evolve.

### Backend Tasks
- [ ] Normalize `Asset`, `Run`, and `ExtractionResult` concepts in code
- [ ] Ensure every upload triggers:
  - [ ] Asset creation
  - [ ] Automatic extraction
  - [ ] System `Run` with logs and progress
- [ ] Enforce DB-as-source-of-truth for object store references
- [ ] Introduce structured run logging (`RunLogEvent` model)
- [ ] Ensure extraction failures are visible but non-blocking

### Frontend Tasks
- [ ] Surface extraction status consistently (`Uploading`, `Processing`, `Ready`, `Needs Attention`)
- [ ] Add basic run visibility (read-only timeline per document)
- [ ] Clearly distinguish raw file vs extracted content in UI

### Acceptance Criteria
- [ ] All uploads create traceable Asset records
- [ ] Extraction runs are visible in UI with structured logs
- [ ] Failed extractions don't block user workflow
- [ ] System is deployable and observable

**Notes**:
- Phase 0 establishes debugging foundation for all future work
- Don't move to Phase 1 until extraction traceability is solid

---

## Phase 1: Asset-Centric UX & Versioning Foundations ⏳ NOT STARTED

**Goal**: Make documents feel stable, inspectable, and version-aware.

### Backend Tasks
- [ ] Introduce asset versioning (immutable raw versions)
- [ ] Support re-extraction on version change
- [ ] Store extraction metadata (timestamps, extractor version)
- [ ] Support manual "re-run extraction" as system run
- [ ] Lay groundwork for bulk upload diffing (fingerprints, paths)

### Frontend Tasks
- [ ] Create consistent Document Detail View with tabs:
  - [ ] Original
  - [ ] Extracted Content
  - [ ] Metadata (canonical-only for now)
  - [ ] History
- [ ] Expose "Re-run extraction" action safely
- [ ] Show asset update history (non-destructive)

### Acceptance Criteria
- [ ] Users can view document history
- [ ] Re-extraction is safe and traceable
- [ ] Document detail view is consistent across all sources

**Dependencies**: Phase 0 complete

---

## Phase 2: Bulk Upload Updates & Collection Health ⏳ NOT STARTED

**Goal**: Eliminate friction for real-world document updates.

### Backend Tasks
- [ ] Implement bulk upload analysis:
  - [ ] Detect unchanged files
  - [ ] Detect updated files (content fingerprint)
  - [ ] Detect new files
  - [ ] Detect missing files (optional, non-destructive)
- [ ] Create new asset versions for updates
- [ ] Trigger automatic re-extraction for updated assets
- [ ] Track collection-level health signals

### Frontend Tasks
- [ ] Folder re-upload UX with single confirmation step
- [ ] Clear preview of detected changes (counts, not per-file)
- [ ] Collection-level health indicators
- [ ] Non-destructive handling of missing files

### Acceptance Criteria
- [ ] Folder re-upload detects changes automatically
- [ ] Users can bulk-update documents with one confirmation
- [ ] No accidental data loss from missing files

**Dependencies**: Phase 1 complete

---

## Phase 3: Flexible Metadata & Experimentation Core ⏳ NOT STARTED

**Goal**: Enable LLM-driven iteration without schema churn.

### Backend Tasks
- [ ] Implement `AssetMetadata` as first-class artifacts
- [ ] Support canonical vs experimental metadata distinction
- [ ] Enable experiment runs that produce metadata variants
- [ ] Add promotion/demotion mechanics (pointer updates)
- [ ] Ensure all metadata-producing activity is run-attributed

### Frontend Tasks
- [ ] Metadata tab with:
  - [ ] Canonical metadata (always visible, trusted)
  - [ ] Experimental metadata (collapsible, attributed)
- [ ] Side-by-side comparison for experiment outputs
- [ ] Explicit "Promote to Canonical" actions
- [ ] Clear attribution to runs/configs

### Acceptance Criteria
- [ ] Users can run experiments without touching production metadata
- [ ] Side-by-side comparison works for summaries, tags, topics
- [ ] Promotion is explicit and traceable

**Dependencies**: Phase 2 complete

**Note**: This is the core differentiation phase - enables iteration without automation

---

## Phase 4: Web Scraping as Durable Data Source ⏳ NOT STARTED

**Goal**: Treat web scraping as institutional memory, not transient crawling.

### Backend Tasks
- [ ] Introduce scrape collections with:
  - [ ] Discovery (page) assets
  - [ ] Durable record assets
- [ ] Support hierarchical path metadata
- [ ] Ensure record-preserving behavior (no auto-deletes)
- [ ] Implement crawl runs and re-crawl semantics
- [ ] Integrate scheduled re-crawls via `ScheduledTask`

### Frontend Tasks
- [ ] Tree-based browsing for scraped collections
- [ ] Clear distinction between pages and captured records
- [ ] Crawl history and status visibility
- [ ] Re-crawl actions at collection and subtree levels

### Acceptance Criteria
- [ ] Scraped records never auto-delete
- [ ] Re-crawl creates new versions, preserves history
- [ ] Hierarchical navigation works intuitively

**Dependencies**: Phase 3 complete

---

## Phase 5: System Maintenance & Scheduling Maturity ⏳ NOT STARTED

**Goal**: Make system self-maintaining and operable long-term.

### Backend Tasks
- [ ] Implement `ScheduledTask` model and scheduler loop
- [ ] Add maintenance runs:
  - [ ] Garbage collection
  - [ ] Orphan detection
  - [ ] Retention enforcement
- [ ] Enforce idempotency and locking
- [ ] Add summary reporting for system runs

### Frontend Tasks
- [ ] Admin/system views for scheduled activity (read-only)
- [ ] Visibility into maintenance outcomes (summaries, not logs)
- [ ] Clear separation of user vs system activity

### Acceptance Criteria
- [ ] System self-maintains without manual intervention
- [ ] Scheduled tasks are observable and debuggable
- [ ] No orphaned objects in production

**Dependencies**: Phase 4 complete

---

## Phase 6: Optional Integrations & Automation ⏳ NOT STARTED

**Goal**: Extend Curatore outward without destabilizing core.

**IMPORTANT**: This phase is OPTIONAL and should NOT block earlier phases.

### Backend Tasks (Optional)
- [ ] Vector DB sync actions
- [ ] OpenWebUI publication
- [ ] External notifications/webhooks
- [ ] Limited automation chaining for stabilized workflows

### Frontend Tasks (Optional)
- [ ] Output destination configuration
- [ ] Sync history and status views
- [ ] Automation opt-in controls

**Dependencies**: Phase 5 complete (but this is optional/future work)

---

## Phase 7: Native SAM.gov Domain Integration ⏳ NOT STARTED

**Goal**: Migrate SAM.gov from scripts into first-class domain pipeline.

### Backend Tasks
- [ ] Introduce `Solicitation` and `Notice` relational models
- [ ] Implement SAM.gov API abstraction layer
- [ ] Convert daily ingest script into scheduled system run
- [ ] Integrate attachment ingestion with asset + extraction pipeline
- [ ] Enable derived metadata and reporting runs

### Frontend Tasks
- [ ] Add SAM.gov collection type
- [ ] Solicitation-centric browsing and filtering
- [ ] Notice history and attachment visibility
- [ ] Executive report access and export

**Dependencies**: Phase 5 complete (needs scheduling maturity)

---

## Key Data Models to Implement (Across Phases)

### Core Models (Phase 0-1)
- `Asset` - Immutable raw content with provenance
- `ExtractionResult` - Canonical extracted content per asset
- `Run` - Execution of logic against extracted content
- `RunLogEvent` - Structured logging for runs
- `RunArtifact` - Outputs produced by runs

### Metadata Models (Phase 3)
- `AssetMetadata` - Flexible, versioned, attributed metadata artifacts

### Scraping Models (Phase 4)
- `ScrapeCollection` - Web scraping projects
- `CrawlRun` - Individual crawl executions
- `PageAsset` - Per-URL snapshots

### Scheduling Models (Phase 5)
- `ScheduledTask` - Recurring task definitions
- `SystemRun` - Link between scheduled tasks and runs

### Domain Models (Phase 7)
- `Solicitation` - SAM.gov opportunity lifecycle
- `Notice` - Time-versioned SAM.gov notices

---

## Object Store Structure (Final State)

```
raw/asset/{asset_id}/                              - Immutable originals
extracted/asset/{asset_id}/v{extractor_version}/   - Canonical extractions
runs/run/{run_id}/artifacts/                       - Run outputs
experiments/experiment/{experiment_id}/variants/   - Experimental outputs
exports/sync/{sync_id}/                            - Published payloads
```

**Critical**: No ad-hoc or user-defined paths permitted.

---

## Session Checklist (Use This Every Session)

1. [ ] Read this progress file (not the full requirements)
2. [ ] Identify current phase and specific task
3. [ ] Reference specific section of UPDATED_DATA_ARCHITECTURE.md if needed
4. [ ] Complete task(s)
5. [ ] Update this file with progress
6. [ ] Note any blockers or decisions needed

---

## Current Blockers / Decisions Needed

*(Update this section as you work)*

- None yet (just starting Phase 0)

---

## Change Log

- **2026-01-28**: Initial progress tracker created, Phase 0 marked as IN PROGRESS
