# SAM.gov Integration

Curatore integrates with SAM.gov (System for Award Management) to track federal contracting opportunities. This document covers the data model, API integration, and key concepts.

## Key Concept: Notices vs Solicitations

**SAM.gov API returns Notices, not Solicitations.** A "notice" is the fundamental unit from the SAM.gov API - it represents a single posting (opportunity, amendment, special notice, etc.).

**Solicitations are our abstraction.** When a notice has a `solicitation_number`, we create a `SamSolicitation` record to group related notices together. Multiple notices (original + amendments) can belong to the same solicitation.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           SAM.GOV DATA MODEL                                     │
└─────────────────────────────────────────────────────────────────────────────────┘

  SAM.gov API                    Curatore Database
      │
      ▼
┌─────────────┐
│   Notice    │─────────┐
│ (has solnum)│         │
└─────────────┘         │     ┌─────────────────┐
                        ├────▶│  SamSolicitation │◀──── Groups notices with same solnum
┌─────────────┐         │     │  (our grouping)  │
│   Notice    │─────────┘     └─────────────────┘
│ (amendment) │                        │
└─────────────┘                        │
                                       ▼
┌─────────────┐               ┌─────────────────┐
│   Notice    │──────────────▶│   SamNotice     │◀──── Each notice becomes a SamNotice
│ (Special)   │               │  solicitation_id│       - With solnum: linked to solicitation
└─────────────┘               │  = NULL for     │       - Without solnum: standalone
  No solnum!                  │  standalone     │
                              └─────────────────┘
```

---

## Notice Types

SAM.gov uses `ptype` codes to identify notice types:

| Type Code | Name | Has Solicitation Number? |
|-----------|------|-------------------------|
| `o` | Solicitation | Yes (usually) |
| `p` | Presolicitation | Yes (usually) |
| `k` | Combined Synopsis/Solicitation | Yes (usually) |
| `r` | Sources Sought | Maybe |
| `s` | Special Notice | **No** - always standalone |
| `g` | Sale of Surplus Property | Maybe |
| `a` | Award Notice | Yes (usually) |
| `u` | Justification (J&A) | Yes (usually) |
| `i` | Intent to Bundle | Maybe |

---

## Standalone Notices

**Special Notices (type "s")** are informational and don't have solicitation numbers. They are stored as:
- `SamNotice` with `solicitation_id = NULL`
- `organization_id` set on the notice itself (not inherited from solicitation)
- Agency info stored directly on the notice (`agency_name`, `bureau_name`, `office_name`)
- Attachments linked to notice via `notice_id` (not `solicitation_id`)

---

## Database Models

| Model | Purpose |
|-------|---------|
| `SamSearch` | Saved search configuration (NAICS codes, PSC codes, departments, etc.) |
| `SamSolicitation` | Groups related notices with same solicitation_number |
| `SamNotice` | Individual notice from SAM.gov (can be standalone or linked to solicitation) |
| `SamAttachment` | File attachment (linked to solicitation and/or notice) |
| `SamAgency` / `SamSubAgency` | Agency hierarchy cache |

---

## Storage Paths

```
# Solicitation-linked attachments
{org_id}/sam/{agency}/{bureau}/solicitations/{sol_number}/attachments/{filename}

# Standalone notice attachments
{org_id}/sam/{agency}/{bureau}/notices/{notice_id}/attachments/{filename}
```

---

## Key Service Files

| File | Purpose |
|------|---------|
| `sam_service.py` | Database operations for SAM entities |
| `sam_pull_service.py` | SAM.gov API integration and data sync |
| `sam_api_usage_service.py` | Rate limiting and API quota tracking |
| `sam_summarization_service.py` | LLM-powered summary generation |

---

## API Endpoints

```
# Searches
GET    /api/v1/sam/searches              # List saved searches
POST   /api/v1/sam/searches              # Create new search
GET    /api/v1/sam/searches/{id}         # Get search details
PATCH  /api/v1/sam/searches/{id}         # Update search
DELETE /api/v1/sam/searches/{id}         # Delete search
POST   /api/v1/sam/searches/{id}/pull    # Trigger manual pull

# Solicitations
GET    /api/v1/sam/solicitations         # List solicitations
GET    /api/v1/sam/solicitations/{id}    # Get solicitation with notices

# Notices
GET    /api/v1/sam/notices               # List notices
GET    /api/v1/sam/notices/{id}          # Get notice details
```

---

## Search Configuration

`SamSearch` records define what to pull from SAM.gov:

```python
class SamSearch:
    name: str                    # User-defined name
    slug: str                    # URL-safe identifier
    naics_codes: List[str]       # NAICS code filters
    psc_codes: List[str]         # PSC code filters
    agency_ids: List[str]        # Agency filters
    keywords: List[str]          # Keyword filters
    set_asides: List[str]        # Set-aside filters
    sync_frequency: str          # 'manual', 'hourly', 'daily'
    automation_config: dict      # Post-sync automation
```

---

## Pull Process

1. **Query SAM.gov API** with search filters
2. **Process each notice**:
   - If has `solicitation_number` → create/update `SamSolicitation`, link notice
   - If no `solicitation_number` → create standalone `SamNotice`
3. **Download attachments** → create `Asset` records, queue extractions
4. **Create Run Group** → track all child extractions
5. **On group completion** → trigger `after_procedure_slug` if configured

---

## Events

| Event | When Emitted |
|-------|--------------|
| `sam_pull.completed` | After SAM.gov pull finishes (before extractions) |
| `sam_pull.group_completed` | After all attachment extractions complete |

---

## Frontend Pages

| Page | Path | Purpose |
|------|------|---------|
| Searches | `/sam/searches` | Manage saved searches |
| Search Detail | `/sam/searches/{id}` | View search with solicitations |
| Setup | `/sam/setup` | Initial setup wizard |
| Solicitations | `/sam/solicitations` | Browse all solicitations |
| Solicitation Detail | `/sam/solicitations/{id}` | View solicitation with notices |
