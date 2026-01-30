# Architecture Refactor Archive

This directory contains documentation from the Curatore v2 architecture refactor project (completed 2026-01-29).

## Files

- **ARCHITECTURE_PROGRESS.md** - Session-by-session progress tracker for the multi-phase refactor
- **UPDATED_DATA_ARCHITECTURE.md** - Full architectural requirements and design decisions
- **PHASE0_TESTING_GUIDE.md** - Testing guide for Phase 0 (Stabilization & Baseline Observability)

## Phases Completed

| Phase | Name | Status |
|-------|------|--------|
| 0 | Stabilization & Baseline Observability | Complete |
| 1 | Asset-Centric UX & Versioning Foundations | Complete |
| 2 | Bulk Upload Updates & Collection Health | Complete |
| 3 | Flexible Metadata & Experimentation Core | Complete |
| 4 | Web Scraping as Durable Data Source | Complete |
| 5 | System Maintenance & Scheduling Maturity | Complete |
| 6 | Native Search with OpenSearch | Complete |
| 6.2 | Optional Integrations (Faceted Search) | Partial |
| 7 | SAM.gov Native Domain Integration | Complete |

## Key Outcomes

- **Asset-centric model**: Documents are now tracked as Assets with version history
- **Run-based execution**: All processing is tracked via Run records with structured logs
- **Automatic extraction**: Documents are automatically converted to Markdown on upload
- **Full-text search**: OpenSearch integration with faceted filtering
- **Web scraping**: Playwright-based crawling with inline extraction
- **SAM.gov integration**: Federal opportunity tracking with AI summaries
- **Scheduled maintenance**: Database-backed tasks with admin controls
- **Job system deprecated**: Replaced by Run-based tracking

## Reference

For current development guidance, see `/CLAUDE.md` in the project root.
