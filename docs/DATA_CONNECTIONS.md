# Data Connections Guide

This document provides comprehensive instructions for implementing new data connections in Curatore v2. A "data connection" is an integration that imports, syncs, or manages external data sources (e.g., Salesforce CRM, SAM.gov, SharePoint, web scraping).

---

## ⚠️ Critical Steps - Don't Skip These!

These are the most commonly missed steps that cause integrations to fail:

| Step | File | What Happens If Missed |
|------|------|------------------------|
| **1. Add to ALL_RUN_TYPES** | `backend/app/api/v1/ops/routers/queue_admin.py` | Jobs won't appear in Job Manager |
| **2. Add Celery queue to worker** | `docker-compose.yml` (worker command) | Tasks sit in Redis queue forever |
| **3. Use explicit task name** | `@celery_app.task(name="app.tasks.xxx")` | Task routing fails silently |
| **4. Use run_log_service for logging** | Import `run_log_service`, NOT `run_service` | `AttributeError: 'RunService' object has no attribute 'log_event'` |
| **5. Recreate worker after adding queue** | `docker-compose stop worker && docker-compose rm -f worker && docker-compose up -d worker` | Worker doesn't consume new queue |
| **6. Add job type config** | `frontend/lib/job-type-config.ts` | Jobs show as "Unknown" type |

**After making changes, always verify with:**
```bash
# Check worker is consuming your queue
docker exec curatore-worker celery -A app.celery_app inspect active_queues 2>/dev/null | grep your_queue

# Check tasks are registered
docker logs curatore-worker 2>&1 | grep your_task_name

# Check Redis queue (should be empty after worker processes)
docker exec curatore-redis redis-cli llen your_queue
```

---

## Overview

Adding a new data connection involves multiple layers of the application:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        DATA CONNECTION ARCHITECTURE                              │
└─────────────────────────────────────────────────────────────────────────────────┘

  DATABASE LAYER          SERVICE LAYER           API LAYER            FRONTEND
       │                       │                      │                    │
       ▼                       ▼                      ▼                    ▼
┌─────────────┐        ┌─────────────────┐    ┌─────────────┐    ┌─────────────────┐
│ SQLAlchemy  │        │ CRUD Service    │    │ FastAPI     │    │ Next.js Pages   │
│ Models      │◀──────▶│ Import Service  │◀──▶│ Router      │◀──▶│ API Client      │
├─────────────┤        ├─────────────────┤    ├─────────────┤    ├─────────────────┤
│ Alembic     │        │ Queue Registry  │    │ Pydantic    │    │ Job Tracking    │
│ Migration   │        │ Celery Task     │    │ Models      │    │ UI Components   │
└─────────────┘        └─────────────────┘    └─────────────┘    └─────────────────┘
                              │
                              ▼
                       ┌─────────────────┐
                       │ Search Indexing │
                       │ File Management │
                       └─────────────────┘
```

## Key Services Quick Reference

### Run Management (CRITICAL - Don't Confuse These!)

| Service | Import | Purpose | When to Use |
|---------|--------|---------|-------------|
| `run_service` | `from app.core.shared.run_service import run_service` | Run **lifecycle** management | Creating runs, updating status, completing/failing runs |
| `run_log_service` | `from app.core.shared.run_log_service import run_log_service` | Run **event logging** | Logging progress, errors, and events DURING job execution |

```python
# ✅ CORRECT PATTERN
from app.core.shared.run_service import run_service
from app.core.shared.run_log_service import run_log_service

# Creating and managing runs (run_service)
run = await run_service.create_run(session, org_id, "my_import", created_by=user_id)
await run_service.update_run_status(session, run.id, "running")
await run_service.complete_run(session, run.id, results_summary={"count": 100})
await run_service.fail_run(session, run.id, "Something went wrong")

# Logging events DURING execution (run_log_service)
await run_log_service.log_event(session, run.id, "INFO", "start", "Starting import")
await run_log_service.log_event(session, run.id, "INFO", "progress", "Processed 50/100")
await run_log_service.log_event(session, run.id, "ERROR", "error", "Failed to parse row 42")

# ❌ WRONG - This method doesn't exist!
await run_service.log_event(...)  # AttributeError!
```

### Other Common Services

| Service | Import | Purpose |
|---------|--------|---------|
| `database_service` | `from app.core.shared.database_service import database_service` | Database session management |
| `minio_service` | `from app.core.storage.minio_service import minio_service` | Object storage (MinIO/S3) |
| `pg_index_service` | `from app.core.search.pg_index_service import pg_index_service` | Search indexing (pgvector) |
| `asset_service` | `from app.core.shared.asset_service import asset_service` | Asset CRUD operations |

## Checklist

Use this checklist when implementing a new data connection:

### Backend - Core
- [ ] Database models in `backend/app/core/database/models.py`
- [ ] Alembic migration in `backend/alembic/versions/`
- [ ] CRUD service in `backend/app/connectors/{name}/{name}_service.py`
- [ ] Import service in `backend/app/connectors/{name}/{name}_import_service.py` (if applicable)
- [ ] Queue definition in `backend/app/core/ops/queue_registry.py`
- [ ] Celery task in `backend/app/core/tasks/{name}.py`
- [ ] Task routing in `backend/app/celery_app.py`
- [ ] Worker queue in `docker-compose.yml`
- [ ] API router in `backend/app/api/v1/data/routers/{name}.py`
- [ ] Router registration in `backend/app/api/v1/data/__init__.py`
- [ ] Run type in `backend/app/api/v1/ops/routers/queue_admin.py` (`ALL_RUN_TYPES`)

### Backend - Search & Indexing
- [ ] MetadataBuilder subclass in `backend/app/core/search/metadata_builders.py` (build_content + build_metadata with namespaced output)
- [ ] Register builder in `metadata_builders.py` `_register_defaults()`
- [ ] Indexing methods in `backend/app/core/search/pg_index_service.py` (index_*(), delete_*_index()) using builder
- [ ] Call indexing in import service after successful import
- [ ] Search method in `backend/app/core/search/pg_search_service.py` (search_*()) with namespaced metadata filters
- [ ] Search API endpoint in `backend/app/api/v1/data/routers/search.py` (POST and GET)
- [ ] Display-friendly labels for source_type in search results

### Backend - Adapter (if using external APIs)
- [ ] Adapter class in `backend/app/connectors/adapters/` or inline config resolution
- [ ] 3-tier config resolution: DB connection → `config.yml` → environment variables
- [ ] Connection type registered for `connection_service` lookup
- [ ] `test_connection()` method for health checks
- [ ] Retry logic with exponential backoff for transient errors

### Backend - CWR Functions
- [ ] Search primitive in `backend/app/cwr/tools/primitives/search/search_{name}.py`
- [ ] Data source primitives in `backend/app/cwr/tools/primitives/{name}/` (if applicable)
- [ ] Compound functions in `backend/app/cwr/tools/compounds/` (if applicable)
- [ ] Function registration in `backend/app/cwr/tools/registry.py` (`_discover_functions()`)
- [ ] ContentItem type mapping in `backend/app/cwr/tools/content/content_item.py`
- [ ] ContentService methods in `backend/app/cwr/tools/content/service.py`
- [ ] Content type registration in `backend/app/cwr/tools/content/registry.py`
- [ ] `get` function `enum_values` updated in `backend/app/cwr/tools/primitives/search/get.py`
- [ ] `query_model` `ALLOWED_MODELS` updated in `backend/app/cwr/tools/primitives/search/query_model.py`
- [ ] Governance fields set correctly (`side_effects`, `payload_profile`, `exposure_profile`, etc.)
- [ ] `discover_data_sources` function updated to query new config tables

### Backend - Metadata Registry
- [ ] Namespace in `backend/app/core/metadata/registry/namespaces.yaml`
- [ ] Field definitions in `backend/app/core/metadata/registry/fields.yaml`
- [ ] Facet definitions and mappings in `backend/app/core/metadata/registry/facets.yaml`
- [ ] Data source entry in `backend/app/core/metadata/registry/data_sources.yaml`
- [ ] Reference data entries in `backend/app/core/metadata/registry/reference_data.yaml` (if applicable)
- [ ] MetadataBuilder subclass in `backend/app/core/search/metadata_builders.py`
- [ ] Builder registration in `metadata_builders.py` `_register_defaults()`

### Frontend - Core
- [ ] TypeScript interfaces in `frontend/lib/api.ts`
- [ ] API client methods in `frontend/lib/api.ts`
- [ ] Job type config in `frontend/lib/job-type-config.ts`
- [ ] Dashboard page at `frontend/app/{name}/page.tsx`
- [ ] List pages at `frontend/app/{name}/{entity}/page.tsx`
- [ ] Detail pages at `frontend/app/{name}/{entity}/[id]/page.tsx`
- [ ] Sidebar navigation in `frontend/components/layout/LeftSidebar.tsx`
- [ ] Job Manager support in `frontend/app/admin/queue/page.tsx`
- [ ] Job detail support in `frontend/app/admin/queue/[runId]/page.tsx`

### Frontend - Search
- [ ] Source type in `sourceTypeConfig` in `frontend/app/search/page.tsx` (name, icon, color)
- [ ] Import Lucide icon for your source type
- [ ] Update search page help text to mention new source
- [ ] Search result card component (if custom display needed)

### Testing & Verification
- [ ] API endpoint tests in `backend/tests/`
- [ ] Import service tests
- [ ] Search indexing verification script
- [ ] Manual verification checklist completed

---

## 1. Database Models

### Location
`backend/app/core/database/models.py`

### Guidelines

1. **Use UUIDs for primary keys**:
```python
from sqlalchemy import Column, String, DateTime, ForeignKey, Index, Text, Boolean, Integer, Float
from sqlalchemy.dialects.postgresql import UUID, JSONB
import uuid

class MyEntity(Base):
    __tablename__ = "my_entities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
```

2. **Always include organization_id** for multi-tenancy:
```python
organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
```

3. **Use external IDs for upsert operations**:
```python
# For Salesforce, use 18-character ID
salesforce_id = Column(String(18), nullable=False, index=True)

# Create unique constraint on (organization_id, external_id)
__table_args__ = (
    Index("ix_my_entities_org_external_id", "organization_id", "salesforce_id", unique=True),
)
```

4. **Use JSONB for flexible/nested data**:
```python
# Address fields
billing_address = Column(JSONB, nullable=True)  # {street, city, state, postal_code, country}

# Flags/options
small_business_flags = Column(JSONB, nullable=True)  # {sba_8a: bool, hubzone: bool, ...}

# Raw data preservation
raw_data = Column(JSONB, nullable=True)  # Store original API response
```

5. **Include timestamps**:
```python
created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
indexed_at = Column(DateTime(timezone=True), nullable=True)  # For search indexing
```

6. **Add future hook columns** for planned integrations:
```python
# Future: Link to SharePoint folder
linked_sharepoint_folder_id = Column(UUID(as_uuid=True), ForeignKey("sharepoint_sync_configs.id"), nullable=True)

# Future: Link to SAM solicitation
linked_sam_solicitation_id = Column(UUID(as_uuid=True), ForeignKey("sam_solicitations.id"), nullable=True)
```

7. **Create appropriate indexes**:
```python
__table_args__ = (
    # Unique constraint
    Index("ix_my_entities_org_external_id", "organization_id", "external_id", unique=True),
    # Filtering indexes
    Index("ix_my_entities_org_type", "organization_id", "entity_type"),
    Index("ix_my_entities_org_status", "organization_id", "status"),
    # Lookup indexes
    Index("ix_my_entities_parent_id", "parent_id"),
)
```

### Example Model

```python
class SalesforceAccount(Base):
    """Salesforce Account record."""
    __tablename__ = "salesforce_accounts"

    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Organization (multi-tenancy)
    organization_id = Column(UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)

    # External ID (for upsert)
    salesforce_id = Column(String(18), nullable=False, index=True)

    # Core fields
    name = Column(String(255), nullable=False, index=True)
    account_type = Column(String(100), nullable=True)
    industry = Column(String(100), nullable=True)

    # Nested data
    billing_address = Column(JSONB, nullable=True)
    raw_data = Column(JSONB, nullable=True)

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    indexed_at = Column(DateTime(timezone=True), nullable=True)

    # Indexes
    __table_args__ = (
        Index("ix_sf_accounts_org_sf_id", "organization_id", "salesforce_id", unique=True),
        Index("ix_sf_accounts_org_type", "organization_id", "account_type"),
    )
```

---

## 2. Alembic Migration

### Location
`backend/alembic/versions/YYYYMMDD_description.py`

### Guidelines

1. **Use descriptive revision IDs and messages**:
```python
revision = "20260205_add_salesforce_integration"
down_revision = "previous_revision_id"
```

2. **Make migrations idempotent** when possible:
```python
def upgrade():
    # Check if table exists before creating
    conn = op.get_bind()
    inspector = sa.inspect(conn)

    if "salesforce_accounts" not in inspector.get_table_names():
        op.create_table(
            "salesforce_accounts",
            # ... columns
        )
```

3. **Create indexes in the migration**:
```python
op.create_index(
    "ix_sf_accounts_org_sf_id",
    "salesforce_accounts",
    ["organization_id", "salesforce_id"],
    unique=True
)
```

4. **Always include downgrade**:
```python
def downgrade():
    op.drop_table("salesforce_opportunities")
    op.drop_table("salesforce_contacts")
    op.drop_table("salesforce_accounts")
```

---

## 3. Service Layer

### CRUD Service

**Location**: `backend/app/connectors/{name}/{name}_service.py`

Provides database operations for the data connection.

```python
"""
Salesforce CRM service for Curatore v2.

Provides CRUD operations for Salesforce Account, Contact, and Opportunity records.
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database.models import SalesforceAccount, SalesforceContact, SalesforceOpportunity

logger = logging.getLogger("curatore.services.salesforce")


class SalesforceService:
    """Service for Salesforce CRM data operations."""

    # =========================================================================
    # UPSERT OPERATIONS (by external ID)
    # =========================================================================

    async def upsert_account(
        self,
        session: AsyncSession,
        organization_id: UUID,
        salesforce_id: str,
        data: Dict[str, Any],
    ) -> SalesforceAccount:
        """Create or update an account by Salesforce ID."""
        # Check for existing
        result = await session.execute(
            select(SalesforceAccount).where(
                and_(
                    SalesforceAccount.organization_id == organization_id,
                    SalesforceAccount.salesforce_id == salesforce_id,
                )
            )
        )
        account = result.scalar_one_or_none()

        if account:
            # Update existing
            for key, value in data.items():
                if hasattr(account, key):
                    setattr(account, key, value)
            account.updated_at = datetime.utcnow()
        else:
            # Create new
            account = SalesforceAccount(
                organization_id=organization_id,
                salesforce_id=salesforce_id,
                **data,
            )
            session.add(account)

        return account

    # =========================================================================
    # READ OPERATIONS
    # =========================================================================

    async def get_account(
        self,
        session: AsyncSession,
        organization_id: UUID,
        account_id: UUID,
    ) -> Optional[SalesforceAccount]:
        """Get account by ID."""
        result = await session.execute(
            select(SalesforceAccount).where(
                and_(
                    SalesforceAccount.organization_id == organization_id,
                    SalesforceAccount.id == account_id,
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_accounts(
        self,
        session: AsyncSession,
        organization_id: UUID,
        keyword: Optional[str] = None,
        account_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[List[SalesforceAccount], int]:
        """List accounts with filtering and pagination."""
        # Base query
        query = select(SalesforceAccount).where(
            SalesforceAccount.organization_id == organization_id
        )

        # Apply filters
        if keyword:
            query = query.where(
                SalesforceAccount.name.ilike(f"%{keyword}%")
            )
        if account_type:
            query = query.where(SalesforceAccount.account_type == account_type)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_query)).scalar() or 0

        # Apply pagination
        query = query.order_by(SalesforceAccount.name).limit(limit).offset(offset)
        result = await session.execute(query)

        return list(result.scalars().all()), total

    # =========================================================================
    # STATISTICS
    # =========================================================================

    async def get_dashboard_stats(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> Dict[str, Any]:
        """Get dashboard statistics."""
        # Account stats
        account_count = await session.execute(
            select(func.count()).where(
                SalesforceAccount.organization_id == organization_id
            )
        )

        return {
            "accounts": {
                "total": account_count.scalar() or 0,
            },
            # ... more stats
        }


# Singleton instance
salesforce_service = SalesforceService()
```

### Import Service

**Location**: `backend/app/connectors/{name}/{name}_import_service.py`

Handles data import from files or external APIs.

```python
"""
Salesforce import service for Curatore v2.

Handles importing Salesforce data from export zip files.
"""
import csv
import io
import logging
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from .salesforce_service import salesforce_service
# IMPORTANT: Use run_log_service for logging, NOT run_service
from app.core.shared.run_log_service import run_log_service

logger = logging.getLogger("curatore.services.salesforce_import")


class SalesforceImportService:
    """Service for importing Salesforce export data."""

    async def import_from_zip(
        self,
        session: AsyncSession,
        organization_id: UUID,
        zip_path: str,
        run_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Import Salesforce data from a zip file.

        Args:
            session: Database session
            organization_id: Organization UUID
            zip_path: Path to the zip file
            run_id: Optional Run ID for progress tracking

        Returns:
            Dict with import statistics
        """
        stats = {
            "accounts": {"processed": 0, "created": 0, "updated": 0, "errors": 0},
            "contacts": {"processed": 0, "created": 0, "updated": 0, "errors": 0},
        }

        # Log start using run_log_service (not run_service!)
        if run_id:
            await run_log_service.log_event(
                session, run_id, "INFO", "import_start",
                f"Starting import from {Path(zip_path).name}"
            )

        # Open and process zip file
        with zipfile.ZipFile(zip_path, 'r') as zf:
            file_list = zf.namelist()

            # Find and process Account CSV
            account_file = self._find_csv(file_list, "Account")
            if account_file:
                account_stats = await self._import_accounts(
                    session, organization_id, zf, account_file, run_id
                )
                stats["accounts"] = account_stats

            await session.commit()

        return stats

    def _find_csv(self, file_list: List[str], entity_name: str) -> Optional[str]:
        """Find CSV file for an entity in the zip."""
        for filename in file_list:
            if entity_name.lower() in filename.lower() and filename.endswith('.csv'):
                return filename
        return None

    async def _import_accounts(
        self,
        session: AsyncSession,
        organization_id: UUID,
        zf: zipfile.ZipFile,
        filename: str,
        run_id: Optional[UUID],
    ) -> Dict[str, int]:
        """Import accounts from CSV."""
        stats = {"processed": 0, "created": 0, "updated": 0, "errors": 0}

        with zf.open(filename) as f:
            # Handle encoding (Salesforce exports often use latin-1)
            try:
                content = f.read().decode('utf-8')
            except UnicodeDecodeError:
                f.seek(0)
                content = f.read().decode('latin-1')

            reader = csv.DictReader(io.StringIO(content))

            for row in reader:
                stats["processed"] += 1
                try:
                    sf_id = row.get("Id", "").strip()
                    if not sf_id or len(sf_id) < 15:
                        continue

                    # Build data dict from CSV row
                    data = {
                        "name": row.get("Name", "").strip(),
                        "account_type": row.get("Type", "").strip() or None,
                        # ... map other fields
                    }

                    # Upsert
                    account = await salesforce_service.upsert_account(
                        session, organization_id, sf_id, data
                    )

                    if account.created_at == account.updated_at:
                        stats["created"] += 1
                    else:
                        stats["updated"] += 1

                except Exception as e:
                    stats["errors"] += 1
                    logger.warning(f"Error importing account: {e}")

        return stats

    # Helper methods for parsing
    def _parse_bool(self, value: str) -> Optional[bool]:
        """Parse boolean from CSV value."""
        if not value:
            return None
        return value.lower() in ('true', '1', 'yes')

    def _parse_date(self, value: str) -> Optional[datetime]:
        """Parse date from CSV value."""
        if not value:
            return None
        for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%Y-%m-%dT%H:%M:%S'):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None

    def _parse_float(self, value: str) -> Optional[float]:
        """Parse float from CSV value."""
        if not value:
            return None
        try:
            return float(value.replace(',', '').replace('$', ''))
        except ValueError:
            return None


# Singleton instance
salesforce_import_service = SalesforceImportService()
```

---

## 4. Queue Registry

### Location
`backend/app/core/ops/queue_registry.py`

### Guidelines

1. **Define a queue class** that extends `QueueDefinition`:
```python
class SalesforceQueue(QueueDefinition):
    """Salesforce CRM data import queue."""

    def __init__(self):
        super().__init__(
            queue_type="salesforce",           # Unique identifier
            celery_queue="salesforce",         # Celery queue name
            run_type_aliases=["salesforce_import"],  # Alternative run_type values
            can_cancel=True,                   # Allow job cancellation
            can_retry=False,                   # No automatic retry
            label="Salesforce",                # UI display name
            description="Salesforce CRM data import",
            icon="database",                   # Lucide icon name
            color="cyan",                      # Tailwind color
            default_max_concurrent=None,       # None = unlimited
            default_timeout_seconds=1800,      # 30 minutes
        )
```

2. **Register in `_register_defaults()`**:
```python
def _register_defaults(self):
    self.register(ExtractionQueue())
    self.register(SamQueue())
    # ... existing queues ...
    self.register(SalesforceQueue())  # Add new queue
```

---

## 5. Celery Task

### Location
`backend/app/core/tasks/{name}.py` (e.g., `salesforce.py`, `forecasts.py`)

### Guidelines

1. **Use explicit task name**:
```python
@celery_app.task(bind=True, name="app.tasks.salesforce_import_task")
def salesforce_import_task(
    self,
    run_id: str,
    organization_id: str,
    zip_path: str,
) -> Dict[str, Any]:
```

2. **Always clean up temp files**:
```python
try:
    result = asyncio.run(
        _execute_import_async(run_id, organization_id, zip_path)
    )
    return result
except Exception as e:
    asyncio.run(_fail_run(run_id, str(e)))
    raise
finally:
    # Clean up temp file
    if zip_path and os.path.exists(zip_path):
        try:
            os.unlink(zip_path)
            logger.info(f"Cleaned up temp file: {zip_path}")
        except Exception as cleanup_err:
            logger.warning(f"Failed to clean up: {cleanup_err}")
```

3. **Use async wrapper pattern**:
```python
async def _execute_import_async(
    run_id: UUID,
    organization_id: UUID,
    zip_path: str,
) -> Dict[str, Any]:
    """Async wrapper for import."""
    async with database_service.get_session() as session:
        # Update run to running
        await run_service.update_run_status(session, run_id, "running")
        await session.commit()

        try:
            result = await import_service.import_from_zip(
                session, organization_id, zip_path, run_id
            )
            await run_service.complete_run(session, run_id, result)
            await session.commit()
            return result
        except Exception as e:
            await session.rollback()
            await run_service.fail_run(session, run_id, str(e))
            await session.commit()
            raise
```

### Task Routing

**Location**: `backend/app/celery_app.py`

1. **Add queue definition**:
```python
app.conf.task_queues = (
    # ... existing queues ...
    Queue("salesforce", routing_key="salesforce"),
)
```

2. **Add task routing**:
```python
task_routes = {
    # ... existing routes ...
    "app.tasks.salesforce_import_task": {"queue": "salesforce"},
}
```

### Docker Compose

**Location**: `docker-compose.yml`

Add queue to worker command:
```yaml
command: >
  celery -A app.celery_app worker -Q processing_priority,extraction,sam,scrape,sharepoint,salesforce,pipeline,maintenance -l info
```

### ⚠️ Worker Restart Requirements

**When you MUST recreate the worker** (not just restart):
- Adding a new Celery queue
- Changing queue routing
- Adding new task files

**Simple restart** (code changes only):
```bash
docker restart curatore-worker
# OR wait for watchmedo to auto-reload (~10 seconds)
```

**Full recreate** (queue changes):
```bash
docker-compose stop worker && docker-compose rm -f worker && docker-compose up -d worker
```

**Verify your queue is being consumed:**
```bash
# List all queues the worker is consuming
docker exec curatore-worker celery -A app.celery_app inspect active_queues 2>/dev/null

# Should show your new queue in the list:
# * {'name': 'salesforce', 'exchange': ...}
```

**If tasks are stuck in Redis:**
```bash
# Check queue length (should decrease as worker processes)
docker exec curatore-redis redis-cli llen salesforce

# If stuck at non-zero and not decreasing, worker isn't consuming the queue
```

---

## 6. API Router

### Location
`backend/app/api/v1/data/routers/{name}.py` (for data connectors)

### Guidelines

1. **Define Pydantic models** for request/response:
```python
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class AccountResponse(BaseModel):
    id: str
    salesforce_id: str
    name: str
    account_type: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

class AccountListResponse(BaseModel):
    items: List[AccountResponse]
    total: int

class ImportResponse(BaseModel):
    run_id: str
    status: str
    message: str
```

2. **Create router with prefix and tags**:
```python
router = APIRouter(prefix="/salesforce", tags=["Salesforce"])
```

3. **Use dependency injection** for auth:
```python
@router.get("/accounts", response_model=AccountListResponse)
async def list_accounts(
    keyword: Optional[str] = None,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
):
```

4. **Handle file uploads** with temp file management:
```python
@router.post("/import", response_model=ImportResponse)
async def import_data(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    # Save to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
        content = await file.read()
        tmp.write(content)
        zip_path = tmp.name

    try:
        # Create run and queue task
        async with database_service.get_session() as session:
            run = await run_service.create_run(
                session=session,
                organization_id=current_user.organization_id,
                run_type="salesforce_import",
                created_by=current_user.id,
                config={"filename": file.filename},
            )
            await session.commit()

            salesforce_import_task.delay(
                run_id=str(run.id),
                organization_id=str(current_user.organization_id),
                zip_path=zip_path,
            )

            return ImportResponse(
                run_id=str(run.id),
                status="pending",
                message=f"Import started for {file.filename}",
            )
    except Exception as e:
        # Clean up on error
        if os.path.exists(zip_path):
            os.unlink(zip_path)
        raise HTTPException(status_code=500, detail=str(e))
```

### Router Registration

**Location**: `backend/app/api/v1/data/__init__.py`

```python
from .routers import salesforce

data_router.include_router(salesforce.router)
```

---

## 7. Job Manager Integration

### Backend: ALL_RUN_TYPES

**Location**: `backend/app/api/v1/ops/routers/queue_admin.py`

Add run type to the list:
```python
ALL_RUN_TYPES = [
    "extraction",
    "sam_pull",
    # ... existing types ...
    "salesforce_import",  # Add new type
]
```

### Frontend: Job Type Config

**Location**: `frontend/lib/job-type-config.ts`

1. **Add to JobType union**:
```typescript
export type JobType =
  | 'sam_pull'
  | 'sharepoint_sync'
  // ... existing types ...
  | 'salesforce_import'
```

2. **Add configuration**:
```typescript
export const JOB_TYPE_CONFIG: Record<JobType, JobTypeConfig> = {
  // ... existing configs ...
  salesforce_import: {
    label: 'Salesforce Import',
    icon: Database,
    color: 'cyan',
    resourceType: 'salesforce',
    hasChildJobs: false,
    phases: ['parsing', 'importing', 'indexing'],
    completedToast: (name) => `Salesforce import completed: ${name}`,
    failedToast: (name, error) => `Salesforce import failed: ${name}${error ? ` - ${error}` : ''}`,
  },
}
```

3. **Add to getJobTypeFromRunType()**:
```typescript
const directMap: Record<string, JobType> = {
  // ... existing mappings ...
  salesforce_import: 'salesforce_import',
}

// Also add alias check
if (runType.startsWith('salesforce_')) return 'salesforce_import'
```

### Frontend: Job Manager Page

**Location**: `frontend/app/admin/queue/page.tsx`

1. **Add icon import**:
```typescript
import { Database } from 'lucide-react'
```

2. **Add to JOB_TYPE_TABS**:
```typescript
const JOB_TYPE_TABS = [
  // ... existing tabs ...
  { value: 'salesforce', label: 'Salesforce', icon: Database },
]
```

3. **Update getQueueType()**:
```typescript
function getQueueType(runType: string): string {
  if (runType.startsWith('salesforce')) return 'salesforce'
  // ... existing mappings ...
}
```

4. **Update getJobTypeColor()**:
```typescript
function getJobTypeColor(runType: string): string {
  switch (queueType) {
    case 'salesforce': return 'cyan'
    // ... existing colors ...
  }
}
```

### Frontend: Job Detail Page

**Location**: `frontend/app/admin/queue/[runId]/page.tsx`

1. **Add icon import**:
```typescript
import { Database } from 'lucide-react'
```

2. **Add to local JOB_TYPE_CONFIG**:
```typescript
const JOB_TYPE_CONFIG: Record<string, { icon: React.ElementType; label: string; color: string }> = {
  // ... existing configs ...
  salesforce_import: { icon: Database, label: 'Salesforce Import', color: 'text-cyan-600 dark:text-cyan-400' },
}
```

---

## 8. Frontend API Client

### Location
`frontend/lib/api.ts`

### Guidelines

1. **Define TypeScript interfaces**:
```typescript
// Statistics
export interface SalesforceStats {
  accounts: {
    total: number
    by_type: Array<{ type: string; count: number }>
  }
  contacts: {
    total: number
    current_employees: number
  }
  opportunities: {
    total: number
    open: number
    won: number
    open_value: number
    won_value: number
    by_stage: Array<{ stage: string; count: number; value: number }>
  }
}

// Entity interfaces
export interface SalesforceAccount {
  id: string
  salesforce_id: string
  name: string
  account_type: string | null
  industry: string | null
  // ... all fields
}

// List response
export interface SalesforceAccountListResponse {
  items: SalesforceAccount[]
  total: number
}

// Import response
export interface SalesforceImportResponse {
  run_id: string
  status: string
  message: string
}
```

2. **Create API object**:
```typescript
export const salesforceApi = {
  // Statistics
  getStats: async (token: string): Promise<SalesforceStats> => {
    const response = await fetch(`${API_BASE_URL}/salesforce/stats`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!response.ok) throw new Error('Failed to fetch stats')
    return response.json()
  },

  // Import
  importData: async (token: string, file: File): Promise<SalesforceImportResponse> => {
    const formData = new FormData()
    formData.append('file', file)

    const response = await fetch(`${API_BASE_URL}/salesforce/import`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    })
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'Import failed')
    }
    return response.json()
  },

  // CRUD operations
  listAccounts: async (
    token: string,
    params: { keyword?: string; limit?: number; offset?: number }
  ): Promise<SalesforceAccountListResponse> => {
    const searchParams = new URLSearchParams()
    if (params.keyword) searchParams.set('keyword', params.keyword)
    if (params.limit) searchParams.set('limit', params.limit.toString())
    if (params.offset) searchParams.set('offset', params.offset.toString())

    const response = await fetch(
      `${API_BASE_URL}/salesforce/accounts?${searchParams}`,
      { headers: { Authorization: `Bearer ${token}` } }
    )
    if (!response.ok) throw new Error('Failed to fetch accounts')
    return response.json()
  },

  getAccount: async (token: string, id: string): Promise<SalesforceAccount> => {
    const response = await fetch(`${API_BASE_URL}/salesforce/accounts/${id}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!response.ok) throw new Error('Failed to fetch account')
    return response.json()
  },
}
```

3. **Add to default export**:
```typescript
export default {
  // ... existing APIs ...
  salesforceApi,
}
```

---

## 9. Frontend Pages

### Dashboard Page

**Location**: `frontend/app/{name}/page.tsx`

Key elements:
- Stats cards with links to list pages
- Import button with file upload
- Drag-and-drop upload zone
- Job tracking via `useActiveJobs`

```typescript
'use client'

import { useState, useCallback, useRef, DragEvent } from 'react'
import { useAuth } from '@/lib/auth-context'
import { useActiveJobs } from '@/lib/context-shims'
import { salesforceApi } from '@/lib/api'

function DashboardContent() {
  const { token } = useAuth()
  const { addJob } = useActiveJobs()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [isDragging, setIsDragging] = useState(false)

  const handleFileUpload = async (file: File) => {
    const result = await salesforceApi.importData(token, file)

    // Track in job monitor
    if (result.run_id) {
      addJob({
        runId: result.run_id,
        jobType: 'salesforce_import',
        displayName: `Import: ${file.name}`,
        resourceId: result.run_id,
        resourceType: 'salesforce',
      })
    }
  }

  // Drag-drop handlers
  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDrop = useCallback(async (e: DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer?.files[0]
    if (file) await handleFileUpload(file)
  }, [])

  return (
    <div
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className={isDragging ? 'border-cyan-500' : ''}
    >
      {/* Stats cards, upload button, etc. */}
    </div>
  )
}
```

### List Page

**Location**: `frontend/app/{name}/{entity}/page.tsx`

Key elements:
- Search/filter controls
- Paginated table
- Row click navigation to detail

### Detail Page

**Location**: `frontend/app/{name}/{entity}/[id]/page.tsx`

Key elements:
- Breadcrumb navigation
- Entity header with key info
- Related data sections
- Action buttons

---

## 10. Sidebar Navigation

### Location
`frontend/components/layout/LeftSidebar.tsx`

1. **Add icon import**:
```typescript
import { Database } from 'lucide-react'
```

2. **Add to appropriate section** (e.g., `acquireNavigation`):
```typescript
const acquireNavigation: NavItem[] = isAuthenticated ? [
  // ... existing items ...
  {
    name: 'Salesforce CRM',
    href: '/salesforce',
    icon: Database,
    current: pathname?.startsWith('/salesforce'),
    gradient: 'from-cyan-500 to-blue-600'
  }
] : []
```

---

## 11. Search Indexing (Optional)

If the data should be searchable, add indexing methods.

### Location
`backend/app/core/search/pg_index_service.py`

```python
async def index_salesforce_account(
    self,
    session: AsyncSession,
    account: SalesforceAccount,
) -> None:
    """Index a Salesforce account for search."""
    # Build searchable text
    text_parts = [account.name]
    if account.description:
        text_parts.append(account.description)
    if account.industry:
        text_parts.append(account.industry)

    content = "\n".join(text_parts)

    # Create single chunk (accounts are typically small)
    await self._index_chunk(
        session=session,
        organization_id=account.organization_id,
        source_type="salesforce_account",
        source_id=str(account.id),
        source_type_filter="salesforce",
        chunk_index=0,
        content=content,
        metadata={
            "name": account.name,
            "account_type": account.account_type,
            "industry": account.industry,
        },
    )

    # Update indexed_at
    account.indexed_at = datetime.utcnow()
```

---

## 12. File Management

### Temp File Handling

1. **Save uploads to temp files** with `delete=False`:
```python
with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
    content = await file.read()
    tmp.write(content)
    zip_path = tmp.name
```

2. **Always clean up in `finally` block**:
```python
finally:
    if zip_path and os.path.exists(zip_path):
        os.unlink(zip_path)
```

3. **Clean up on API errors** before raising:
```python
except Exception as e:
    if os.path.exists(zip_path):
        os.unlink(zip_path)
    raise HTTPException(...)
```

### Object Storage (for permanent files)

For files that should persist (like attachments), use MinIO:

```python
from app.core.storage.minio_service import minio_service

# Upload
await minio_service.upload_file(
    bucket="curatore-uploads",
    key=f"{org_id}/salesforce/attachments/{filename}",
    data=file_content,
    content_type="application/pdf",
)

# Download
content = await minio_service.download_file(
    bucket="curatore-uploads",
    key=storage_key,
)
```

---

## 13. Testing & Verification

### Pre-Flight Checks

Before testing, verify the infrastructure is set up correctly:

```bash
# 1. Check worker is consuming your queue
docker exec curatore-worker celery -A app.celery_app inspect active_queues 2>/dev/null | grep your_queue_name
# Expected: Shows your queue in the list

# 2. Check task is registered
docker logs curatore-worker 2>&1 | grep "your_task_name"
# Expected: "  . app.tasks.your_task_name"

# 3. Check run type is in ALL_RUN_TYPES
grep -r "your_run_type" backend/app/api/v1/routers/queue_admin.py
# Expected: Shows your run type in ALL_RUN_TYPES list

# 4. Check job type config exists
grep -r "your_job_type" frontend/lib/job-type-config.ts
# Expected: Shows your job type configuration
```

### Testing Checklist

| # | Check | How to Verify | Expected Result |
|---|-------|---------------|-----------------|
| 1 | Database migration | `docker exec curatore-backend alembic upgrade head` | No errors |
| 2 | API endpoints | Visit `http://localhost:8000/docs`, test endpoints | 200 responses |
| 3 | Import starts | Upload file, check response | Returns `run_id` |
| 4 | Task picked up | `docker exec curatore-redis redis-cli llen your_queue` | 0 (processed) |
| 5 | Job in Job Manager | Visit `http://localhost:3000/admin/queue` | Job visible |
| 6 | Job in status bar | Check bottom status bar | Shows running/pending |
| 7 | Job completes | Wait for completion | Status changes to completed |
| 8 | Temp files cleaned | `ls /tmp/tmp*.zip` (in container) | No leftover files |
| 9 | Data imported | Check API list endpoints | Data returned |
| 10 | Notifications work | Complete/fail a job | Toast appears |

### Quick Smoke Test

```bash
# 1. Start fresh
docker-compose stop worker && docker-compose rm -f worker && docker-compose up -d worker

# 2. Wait for worker to be ready
sleep 15

# 3. Verify queue is active
docker exec curatore-worker celery -A app.celery_app inspect active_queues 2>/dev/null | grep salesforce

# 4. Upload a test file via API or UI

# 5. Watch worker logs
docker logs -f curatore-worker 2>&1 | grep -i salesforce

# 6. Check job completed in database
docker exec curatore-backend python -c "
import asyncio
from app.services.database_service import database_service
from sqlalchemy import text
async def check():
    async with database_service.get_session() as session:
        result = await session.execute(
            text(\"SELECT status, error_message FROM runs WHERE run_type='salesforce_import' ORDER BY created_at DESC LIMIT 1\")
        )
        row = result.fetchone()
        print(f'Status: {row[0]}, Error: {row[1]}')
asyncio.run(check())
"
```

---

## Common Pitfalls

1. **Using wrong service for run logging** - Use `run_log_service.log_event()`, NOT `run_service`. The `run_service` handles run CRUD operations (create, update status, complete, fail). The `run_log_service` handles structured logging events.
   ```python
   # CORRECT
   from app.core.shared.run_log_service import run_log_service
   await run_log_service.log_event(session, run_id, "INFO", "my_event", "Message")

   # WRONG - run_service doesn't have log_event()
   from app.core.shared.run_service import run_service
   await run_service.log_event(...)  # This will fail!
   ```

2. **Forgetting to restart/recreate the worker** after adding new Celery queues - Use `docker-compose stop worker && docker-compose rm -f worker && docker-compose up -d worker` to ensure new queues are consumed.

3. **Missing task name** in `@celery_app.task(name="...")` decorator - Always use explicit task names for reliable routing.

4. **Not adding run_type to `ALL_RUN_TYPES`** in queue_admin.py - Jobs won't appear in Job Manager.

5. **Temp files not cleaned up** - Always use `finally` blocks in Celery tasks.

6. **Job monitor showing stale jobs** - Filter for active statuses only (exclude completed, failed, cancelled, timed_out).

7. **Missing icon imports** in frontend components.

8. **Encoding issues** with CSV imports - Try latin-1 fallback for Salesforce exports.

9. **Missing await** on async database operations.

10. **Wrong parameter names in run_service.create_run()** - Use `created_by` (not `started_by`) and `config` (not `metadata`).

---

## Troubleshooting

### Job stuck in "pending" status

**Symptoms**: Job created but never starts, stays pending forever.

**Diagnosis**:
```bash
# Check if task is in Redis queue
docker exec curatore-redis redis-cli llen your_queue
# If > 0, worker isn't consuming the queue

# Check if worker is consuming the queue
docker exec curatore-worker celery -A app.celery_app inspect active_queues 2>/dev/null | grep your_queue
# If not listed, queue isn't being consumed
```

**Solution**: Recreate the worker:
```bash
docker-compose stop worker && docker-compose rm -f worker && docker-compose up -d worker
```

### Job fails with "AttributeError: 'RunService' object has no attribute 'log_event'"

**Cause**: Using `run_service.log_event()` instead of `run_log_service.log_event()`.

**Solution**: Change your import and method call:
```python
# Wrong
from app.core.shared.run_service import run_service
await run_service.log_event(...)

# Correct
from app.core.shared.run_log_service import run_log_service
await run_log_service.log_event(...)
```

### Job doesn't appear in Job Manager

**Cause**: Run type not added to `ALL_RUN_TYPES`.

**Solution**: Add your run type to `backend/app/api/v1/ops/routers/queue_admin.py`:
```python
ALL_RUN_TYPES = [
    # ... existing types ...
    "your_import_type",  # Add this
]
```

### Job shows as "Unknown" type in frontend

**Cause**: Missing job type configuration in frontend.

**Solution**: Add to `frontend/lib/job-type-config.ts`:
```typescript
export const JOB_TYPE_CONFIG = {
  // ... existing configs ...
  your_import_type: {
    label: 'Your Import',
    icon: YourIcon,
    color: 'cyan',
    // ... etc
  },
}
```

### Task routing not working

**Symptoms**: Task goes to wrong queue or default queue.

**Diagnosis**:
```bash
# Check task routing in celery config
docker exec curatore-worker python -c "from app.celery_app import app; print(app.conf.task_routes)"
```

**Solution**: Ensure task routing is configured in `backend/app/celery_app.py`:
```python
task_routes = {
    "app.tasks.your_task": {"queue": "your_queue"},
}
```

### Temp files not cleaned up

**Symptoms**: `/tmp` fills up with old import files.

**Solution**: Always use `finally` block in Celery tasks:
```python
@celery_app.task(bind=True, name="app.tasks.your_task")
def your_task(self, run_id, zip_path):
    try:
        # ... do work ...
    except Exception as e:
        # ... handle error ...
        raise
    finally:
        # ALWAYS clean up, even on failure
        if zip_path and os.path.exists(zip_path):
            os.unlink(zip_path)
```

---

## 14. CWR Functions (Primitives & Compounds)

Data connections should integrate with the Curatore Workflow Runtime (CWR) to enable LLM-powered workflows, procedures, and pipelines. This requires creating CWR functions, registering content types, and ensuring proper governance metadata.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           CWR FUNCTION ARCHITECTURE                              │
└─────────────────────────────────────────────────────────────────────────────────┘

  FUNCTION DEFINITION              RUNTIME                      CONTRACTS
       │                             │                              │
       ▼                             ▼                              ▼
┌─────────────┐             ┌─────────────────┐            ┌─────────────────┐
│ FunctionMeta │            │ FunctionContext  │            │ ToolContract    │
│ (governance) │            │ (services, DB,  │            │ (JSON Schema)   │
│              │            │  template engine)│            │ Auto-generated  │
├─────────────┤            ├─────────────────┤            ├─────────────────┤
│ BaseFunction │──execute──▶│ FunctionResult  │            │ ContractGen     │
│ (execute())  │            │ (data, status)  │            │ (from Meta)     │
└─────────────┘            └─────────────────┘            └─────────────────┘
       │                                                         │
       ▼                                                         ▼
┌─────────────┐                                          ┌─────────────────┐
│ Registry    │                                          │ Procedure       │
│ (discovery) │                                          │ Validator       │
└─────────────┘                                          └─────────────────┘
```

### Key Base Classes

All classes are in `backend/app/cwr/tools/base.py`.

**FunctionCategory** (enum):

| Value | Purpose |
|-------|---------|
| `SEARCH` | Search/retrieval functions (search_assets, get_content, etc.) |
| `LLM` | Functions that call LLM services (generate, extract, summarize) |
| `OUTPUT` | Side-effect functions (update_metadata, create_artifact) |
| `NOTIFY` | Notification functions (send_email, webhook) |
| `DATA` | External data source operations (SharePoint, Salesforce) |
| `COMPOUND` | Multi-step orchestration functions |
| `FLOW` | Flow control (if_branch, switch_branch, parallel, foreach) |
| `UTILITY` | Utility functions |
| `LOGIC` | Logic functions |

**ParameterDoc** (dataclass):

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | -- | Parameter name (snake_case) |
| `type` | `str` | -- | Type: `"str"`, `"int"`, `"float"`, `"bool"`, `"list[str]"`, `"list[dict]"`, `"dict"`, `"any"` |
| `description` | `str` | -- | Human-readable description |
| `required` | `bool` | `True` | Whether parameter is mandatory. Optional params with `None` values are treated as absent. |
| `default` | `Any` | `None` | Default value |
| `enum_values` | `Optional[List[str]]` | `None` | Allowed values (validated at runtime; for arrays, validates each item) |
| `example` | `Any` | `None` | Example value for documentation |

**OutputFieldDoc** / **OutputSchema** / **OutputVariant** (dataclasses):

```python
OutputFieldDoc(name="title", type="str", description="Document title", example="RFP-2026", nullable=False)

OutputSchema(
    type="list[ContentItem]",
    description="Search results as ContentItems",
    fields=[OutputFieldDoc(...)],
    example=None,
)

OutputVariant(mode="single", condition="when single ID provided", schema=OutputSchema(...))
```

**FunctionMeta** — all governance fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | -- | Unique function name (snake_case) |
| `category` | `FunctionCategory` | -- | Category enum |
| `description` | `str` | -- | Description for catalog and AI procedure generator |
| `parameters` | `List[ParameterDoc]` | `[]` | Parameter documentation |
| `returns` | `str` | `"FunctionResult"` | Return type description |
| `examples` | `List[Dict]` | `[]` | Usage examples (`{description, params}`) |
| `tags` | `List[str]` | `[]` | Categorization tags |
| `version` | `str` | `"1.0.0"` | Semantic version |
| `requires_llm` | `bool` | `False` | Needs LLM connection |
| `requires_session` | `bool` | `True` | Needs database session |
| `output_schema` | `Optional[OutputSchema]` | `None` | Machine-readable output structure |
| `output_variants` | `List[OutputVariant]` | `[]` | Alternative output schemas for dual-mode functions |
| **`side_effects`** | `bool` | `False` | Modifies external state (DB writes, email, artifacts). AI generator places these late in workflows. |
| **`is_primitive`** | `bool` | `True` | `True` = atomic operation, `False` = compound (orchestrates sub-steps) |
| **`payload_profile`** | `str` | `"full"` | `"thin"` = IDs/titles/scores, `"full"` = complete data, `"summary"` = condensed. AI generator adds `get_content` after `thin` functions before LLM steps. |
| **`exposure_profile`** | `Dict` | `{"procedure": True, "agent": True}` | Access policy for where the function can be used |

**FunctionResult** — standard return wrapper:

```python
FunctionResult.success_result(data=items, message="Found 5 results", items_processed=5, metadata={"query": "test"})
FunctionResult.failed_result(error="Not found", message="No results")
FunctionResult.partial_result(data=items, items_processed=10, items_failed=2)
FunctionResult.skipped_result(message="No input provided")
```

### Governance Field Guidelines

| Scenario | `side_effects` | `payload_profile` | `is_primitive` | `requires_llm` |
|----------|---------------|-------------------|----------------|----------------|
| Search returning summaries | `False` | `"thin"` | `True` | `False` |
| Get/retrieve with full content | `False` | `"full"` | `True` | `False` |
| Discovery/catalog functions | `False` | `"full"` | `True` | `False` |
| Data source read (SharePoint) | `False` | `"full"` | `True` | `False` |
| Update metadata / create artifact | `True` | `"full"` | `True` | `False` |
| Send email / webhook | `True` | `"full"` | `True` | `False` |
| LLM-powered multi-step analysis | `True` | `"full"` | `False` | `True` |

### Creating a Primitive Function

**Location**: `backend/app/cwr/tools/primitives/<category>/`

Primitive functions are single atomic operations. Most data connections need a **search primitive**.

```python
"""
search_my_data — Search My Data records using hybrid full-text + semantic search.

Returns thin summaries with relevance scores. Use get_content() to retrieve
full content for LLM consumption.
"""
from typing import Any, Dict, List, Optional
import logging

from ...base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
    OutputSchema,
    OutputFieldDoc,
)
from ...context import FunctionContext
from ...content import ContentItem

logger = logging.getLogger("curatore.functions.search.search_my_data")


class SearchMyDataFunction(BaseFunction):
    """Search My Data records."""

    meta = FunctionMeta(
        name="search_my_data",
        category=FunctionCategory.SEARCH,
        description=(
            "Search My Data records using full-text and semantic search. "
            "Returns record summaries with relevance scores. To read full content, "
            "use get_content(asset_ids=[...]) with IDs from these results. "
            "This searches My Data only — use discover_data_sources to see all "
            "available data sources and the appropriate search tool for each."
        ),
        parameters=[
            ParameterDoc(
                name="query",
                type="str",
                description="Search query. Use keywords, not filters. Example: 'cloud migration'",
                required=False,
            ),
            ParameterDoc(
                name="entity_types",
                type="list[str]",
                description="Entity types to include",
                required=False,
                default=["type_a", "type_b"],
                enum_values=["type_a", "type_b", "type_c"],
            ),
            ParameterDoc(
                name="facet_filters",
                type="dict",
                description="Cross-domain facet filters. Example: {\"agency\": \"GSA\"}",
                required=False,
            ),
            ParameterDoc(
                name="limit",
                type="int",
                description="Maximum results (1–100)",
                required=False,
                default=20,
            ),
        ],
        returns="list[ContentItem]: Search results with relevance scores",
        output_schema=OutputSchema(
            type="list[ContentItem]",
            description="My Data search results",
            fields=[
                OutputFieldDoc(name="id", type="str", description="Record UUID"),
                OutputFieldDoc(name="title", type="str", description="Record title"),
                OutputFieldDoc(name="score", type="float", description="Relevance score"),
                OutputFieldDoc(name="category", type="str", description="Record category", nullable=True),
            ],
        ),
        tags=["search", "my_data", "hybrid"],
        requires_llm=False,
        side_effects=False,
        is_primitive=True,
        payload_profile="thin",
        examples=[
            {
                "description": "Search by keyword",
                "params": {"query": "cloud migration"},
            },
            {
                "description": "Filter by entity type",
                "params": {"query": "security", "entity_types": ["type_a"]},
            },
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute search."""
        query = params.get("query")
        entity_types = params.get("entity_types") or ["type_a", "type_b"]
        facet_filters = params.get("facet_filters")
        limit_val = params.get("limit", 20)
        if isinstance(limit_val, str):
            limit_val = int(limit_val) if limit_val else 20
        limit = min(limit_val, 100)

        try:
            results: List[ContentItem] = []

            # Use ctx.search_service for hybrid search
            search_results = await ctx.search_service.search_my_data(
                session=ctx.session,
                organization_id=ctx.organization_id,
                query=query,
                entity_types=entity_types,
                facet_filters=facet_filters,
                limit=limit,
            )

            for hit in search_results.hits:
                results.append(ContentItem(
                    id=str(hit.source_id),
                    type="my_data_record",
                    display_type="My Data",
                    title=hit.title or "",
                    fields={
                        "score": hit.score,
                        "category": hit.metadata.get("category"),
                        "highlights": hit.highlights,
                    },
                ))

            return FunctionResult.success_result(
                data=results,
                message=f"Found {len(results)} records",
                metadata={
                    "query": query,
                    "total_found": search_results.total,
                    "result_type": "ContentItem",
                    "filters_applied": {"entity_types": entity_types},
                },
                items_processed=len(results),
            )

        except Exception as e:
            logger.exception(f"Search failed: {e}")
            return FunctionResult.failed_result(
                error=str(e),
                message="Search failed",
            )
```

**Key conventions for search primitives:**
- Always `payload_profile="thin"` — return IDs/titles/scores, not full content
- Always `side_effects=False`
- Return `List[ContentItem]` as `data`
- Include `metadata` with query details, `total_found`, `result_type`, `filters_applied`
- Description must explain what to use next (e.g., "use get_content() with IDs from these results")
- Cap limits: `min(params.get("limit", 20), 100)`
- Handle string-to-int coercion for Jinja2-rendered values

**Name resolution pattern** — for user-friendly identifiers:
```python
# Support "site_name" that auto-resolves to sync_config_ids
site_name = params.get("site_name")
if site_name:
    # Exact match first
    config = await session.execute(
        select(SharePointSyncConfig).where(
            func.lower(SharePointSyncConfig.site_name) == site_name.lower()
        )
    )
    if not config:
        # Fallback to partial match
        config = await session.execute(
            select(SharePointSyncConfig).where(
                SharePointSyncConfig.site_name.ilike(f"%{site_name}%")
            )
        )
```

### Creating a Compound Function

**Location**: `backend/app/cwr/tools/compounds/`

Compound functions orchestrate multiple sub-operations. They have `is_primitive=False` and `category=FunctionCategory.COMPOUND`.

```python
"""
analyze_my_data — Multi-step analysis of My Data records using LLM.
"""
from typing import Any, Dict, Optional
import logging

from ..base import (
    BaseFunction,
    FunctionMeta,
    FunctionCategory,
    FunctionResult,
    ParameterDoc,
    OutputSchema,
    OutputFieldDoc,
)
from ..context import FunctionContext
from ..content import ContentItem

logger = logging.getLogger("curatore.functions.compounds.analyze_my_data")


class AnalyzeMyDataFunction(BaseFunction):
    """Analyze My Data records using LLM."""

    meta = FunctionMeta(
        name="analyze_my_data",
        category=FunctionCategory.COMPOUND,
        description="Multi-step analysis of My Data records. Fetches record, checks for cached analysis, calls LLM if needed.",
        parameters=[
            ParameterDoc(name="record_id", type="str", description="Record UUID", required=True),
            ParameterDoc(name="depth", type="str", description="Analysis depth", required=False, default="brief", enum_values=["brief", "detailed"]),
        ],
        returns="ContentItem: Analysis result",
        output_schema=OutputSchema(
            type="dict",
            description="Analysis result",
            fields=[
                OutputFieldDoc(name="record_id", type="str", description="Analyzed record ID"),
                OutputFieldDoc(name="analysis", type="str", description="LLM analysis text"),
                OutputFieldDoc(name="model", type="str", description="Model used"),
            ],
        ),
        tags=["compound", "analysis", "my_data", "llm"],
        requires_llm=True,
        side_effects=True,       # Saves analysis to database
        is_primitive=False,       # Multi-step compound
        payload_profile="full",
        examples=[
            {"description": "Brief analysis", "params": {"record_id": "uuid", "depth": "brief"}},
        ],
    )

    async def execute(self, ctx: FunctionContext, **params) -> FunctionResult:
        """Execute multi-step analysis."""
        record_id = params["record_id"]
        depth = params.get("depth", "brief")

        try:
            # Step 1: Fetch the record
            record = await self._fetch_record(ctx, record_id)
            if not record:
                return FunctionResult.failed_result(error=f"Record {record_id} not found")

            # Step 2: Check for cached analysis (avoid redundant LLM calls)
            cached = await self._get_cached_analysis(ctx, record_id, depth)
            if cached:
                return FunctionResult.success_result(
                    data=cached,
                    message="Returned cached analysis",
                )

            # Step 3: Check LLM availability
            if not ctx.llm_service or not ctx.llm_service.is_available:
                return FunctionResult.failed_result(error="LLM service not available")

            # Step 4: Build prompt and call LLM
            prompt = self._build_prompt(record, depth)
            response = await ctx.llm_service.generate(prompt)

            # Step 5: Save analysis (side effect)
            if not ctx.dry_run:
                await self._save_analysis(ctx, record_id, response, depth)

            return FunctionResult.success_result(
                data={"record_id": record_id, "analysis": response, "model": "..."},
                message=f"Completed {depth} analysis",
                items_processed=1,
            )

        except Exception as e:
            logger.exception(f"Analysis failed: {e}")
            return FunctionResult.failed_result(error=str(e))
```

**Key conventions for compound functions:**
- Always `is_primitive=False`, `category=FunctionCategory.COMPOUND`
- Set `requires_llm=True` if any step calls the LLM
- Set `side_effects=True` if any step writes data
- Check `ctx.dry_run` before performing side effects
- Check `ctx.llm_service.is_available` before LLM calls
- Cache results when possible to avoid redundant LLM calls

### Creating Data Source Functions

**Location**: `backend/app/cwr/tools/primitives/<source_name>/`

Data source functions interact with external APIs (e.g., SharePoint Graph API). They use `category=FunctionCategory.DATA`.

```python
class MySourceGetInfoFunction(BaseFunction):
    meta = FunctionMeta(
        name="my_source_get_info",
        category=FunctionCategory.DATA,
        description="Get metadata from My Source API",
        parameters=[
            ParameterDoc(name="url", type="str", description="Source URL", required=False),
            ParameterDoc(name="config_id", type="str", description="Sync config UUID", required=False),
        ],
        # ...
        side_effects=False,      # Read-only
        is_primitive=True,
        payload_profile="full",  # Returns complete metadata
    )
```

### FunctionContext — What's Available at Runtime

`FunctionContext` (`backend/app/cwr/tools/context.py`) provides lazy-loaded service accessors:

| Property | Service | Purpose |
|----------|---------|---------|
| `session` | `AsyncSession` | Database session |
| `organization_id` | `UUID` | Current organization |
| `user_id` | `Optional[UUID]` | Triggering user |
| `run_id` | `Optional[UUID]` | Current run ID |
| `dry_run` | `bool` | Skip side effects if `True` |
| `llm_service` | LLM operations | Chat completions, embeddings |
| `search_service` | `PgSearchService` | Hybrid search |
| `minio_service` | MinIO/S3 | Object storage |
| `asset_service` | `AssetService` | Asset CRUD |
| `run_service` | Run tracking | Run lifecycle |
| `sam_service` | `SamService` | SAM.gov API |
| `content_service` | `ContentService` | Type-agnostic content retrieval |
| `facet_reference_service` | Facet aliases | Cross-source naming resolution |

Template rendering is built in:
- `ctx.render_template(template_str)` — Renders Jinja2 with access to `params`, `steps`, `org_id`, `now()`, `today()`
- `ctx.render_params(params_dict)` — Recursively renders all string values; preserves data types for pure expressions like `{{ steps.data }}`

### ContentItem — Universal Content Wrapper

`ContentItem` (`backend/app/cwr/tools/content/content_item.py`) is the standard container:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Unique identifier |
| `type` | `str` | Content type: `"asset"`, `"solicitation"`, `"notice"`, `"salesforce_account"`, etc. |
| `display_type` | `str` | Human-friendly label: `"Document"`, `"Account"`, `"Opportunity"` |
| `title` | `Optional[str]` | Display title |
| `text` | `Optional[str]` | Primary text content (for LLM consumption) |
| `text_format` | `str` | `"markdown"` or `"json"` |
| `fields` | `Dict[str, Any]` | Structured data fields from source model |
| `metadata` | `Dict[str, Any]` | Additional metadata (scores, timestamps) |
| `children` | `List[ContentItem]` | Nested items (e.g., attachments) |

Jinja2 templates can access fields directly: `{{ item.source_url }}` maps to `item.fields["source_url"]`.

### ContentTypeRegistry

**Location**: `backend/app/cwr/tools/content/registry.py`

Register your content types for the `ContentService` to support `get()` and `search()`:

```python
CONTENT_TYPE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "my_data_record": {
        "formal_name": "My Data Record",
        "model": "MyDataRecord",
        "has_text": True,
        "text_source": "record",
        "text_format": "json",
        "children": [],
        "display_names": {"default": "Record", "search": "My Data Record"},
        "fields": {
            "external_id": "external_id",
            "name": "name",
            "category": "category",
        },
        "metadata_fields": {"raw_data": "raw_data", "created_at": "created_at"},
        "title_field": "name",
    },
}
```

### Function Registration

**Location**: `backend/app/cwr/tools/registry.py`

Add your function to `_discover_functions()`:

```python
def _discover_functions(self):
    # ... existing imports ...

    # My Data functions
    from .primitives.search.search_my_data import SearchMyDataFunction
    self.register(SearchMyDataFunction)

    # My Data source functions (if applicable)
    from .primitives.my_source.my_source_get_info import MySourceGetInfoFunction
    self.register(MySourceGetInfoFunction)
```

Also update these existing functions:

1. **`get` function** (`primitives/search/get.py`) — Add content types to `enum_values`:
```python
enum_values=["asset", "solicitation", "notice", "my_data_record"]
```

2. **`query_model` function** (`primitives/search/query_model.py`) — Add models to `ALLOWED_MODELS`:
```python
ALLOWED_MODELS = {
    # ... existing ...
    "MyDataRecord": "app.database.models.MyDataRecord",
}
```

3. **`discover_data_sources` function** (`primitives/search/discover_data_sources.py`) — Query your config tables so the AI knows about configured instances.

### Tool Contracts (Auto-Generated)

Tool contracts are auto-generated from `FunctionMeta` by `ContractGenerator` (`backend/app/cwr/contracts/tool_contracts.py`). You do **not** need to create contracts manually.

The generated contract includes:
- `input_schema` — JSON Schema from `parameters` list
- `output_schema` — JSON Schema from `output_schema`
- All governance fields (`side_effects`, `payload_profile`, `exposure_profile`, etc.)

The AI procedure generator and procedure validator both use these contracts to:
- Place `side_effects=True` functions late in workflows
- Insert `get_content` steps after `payload_profile="thin"` search functions
- Guard `send_email`/`webhook` with conditionals
- Validate parameter types and required fields

### Description Writing Convention

The `description` field in `FunctionMeta` is critical — the AI procedure generator uses it to select functions. Include:

1. **What the function does** in one sentence
2. **What it returns** (thin summaries vs full data)
3. **What to do next** (e.g., "use get_content() with IDs from these results")
4. **What NOT to do** (e.g., "Do NOT pass solicitation IDs")
5. **What other functions to use** for related tasks

Example:
```python
description=(
    "Search document assets using full-text and semantic search. "
    "Returns document summaries with relevance scores. To read full document content, "
    "use get_content(asset_ids=[...]) with IDs from these results. "
    "This tool searches documents only — use discover_data_sources to see all available "
    "data sources and the appropriate search tool for each."
)
```

### CWR Integration Checklist

| Step | File | What to Do |
|------|------|------------|
| 1 | `primitives/search/search_{name}.py` | Create search primitive |
| 2 | `primitives/{name}/` | Create data source functions (optional) |
| 3 | `compounds/` | Create compound functions (optional) |
| 4 | `registry.py` | Register all functions in `_discover_functions()` |
| 5 | `content/registry.py` | Register content types |
| 6 | `primitives/search/get.py` | Add to `item_type` enum_values |
| 7 | `primitives/search/query_model.py` | Add to `ALLOWED_MODELS` |
| 8 | `primitives/search/discover_data_sources.py` | Query config tables |

---

## 15. MinIO Temp Bucket Pattern

For data connections that involve file uploads (e.g., importing zip files), use MinIO temp bucket instead of local filesystem. This enables horizontal scaling across multiple worker containers.

### Why Not Local Filesystem?

```
❌ Local Temp File Pattern (doesn't scale):

Backend Container           Worker Container
┌─────────────────┐        ┌─────────────────┐
│ Upload file to  │        │ Task tries to   │
│ /tmp/import.zip │───X────│ read /tmp/...   │
└─────────────────┘        └─────────────────┘
                           File doesn't exist!
                           Different filesystem!
```

```
✅ MinIO Temp Bucket Pattern (scales horizontally):

Backend Container           MinIO             Worker Container
┌─────────────────┐        ┌──────┐          ┌─────────────────┐
│ Upload to MinIO │───────▶│ temp │◀─────────│ Download from   │
│ temp bucket     │        │bucket│          │ MinIO           │
└─────────────────┘        └──────┘          └─────────────────┘
                           Shared storage!
                           Works with N workers!
```

### API Router Implementation

```python
from io import BytesIO
import uuid as uuid_module

@router.post("/import")
async def import_data(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    minio: MinioService = Depends(get_minio_service),
):
    content = await file.read()

    # Upload to MinIO temp bucket (NOT local filesystem)
    minio_key = f"{current_user.organization_id}/my_data/imports/{uuid_module.uuid4().hex}.zip"
    minio.put_object(
        bucket=minio.bucket_temp,  # Temp bucket has auto-cleanup lifecycle
        key=minio_key,
        data=BytesIO(content),
        length=len(content),
        content_type="application/zip",
        metadata={"original_filename": file.filename or "export.zip"},
    )

    # Create run record (store MinIO key in config for tracking)
    async with database_service.get_session() as session:
        run = await run_service.create_run(
            session=session,
            organization_id=current_user.organization_id,
            run_type="my_import",
            created_by=current_user.id,
            config={
                "filename": file.filename,
                "file_size": len(content),
                "minio_key": minio_key,  # Track where file is stored
            },
        )
        await session.commit()

        # Queue task with MinIO key (NOT file path)
        my_import_task.delay(
            run_id=str(run.id),
            organization_id=str(current_user.organization_id),
            minio_key=minio_key,  # Pass MinIO key, not file path
        )

        return {"run_id": str(run.id), "status": "pending"}
```

### Celery Task Implementation

```python
@celery_app.task(bind=True, name="app.tasks.my_import_task")
def my_import_task(
    self,
    run_id: str,
    organization_id: str,
    minio_key: str,  # MinIO key, not file path
):
    """Import task that downloads from MinIO."""
    local_temp_path = None

    try:
        # Download from MinIO to local temp file for processing
        minio = MinioService()
        zip_content = minio.get_object(minio.bucket_temp, minio_key)

        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp:
            tmp.write(zip_content.getvalue())
            local_temp_path = tmp.name

        # Process the file
        result = asyncio.run(
            _execute_import_async(run_id, organization_id, local_temp_path)
        )
        return result

    except Exception as e:
        asyncio.run(_fail_run(run_id, str(e)))
        raise

    finally:
        # Clean up BOTH local temp file AND MinIO object
        if local_temp_path and os.path.exists(local_temp_path):
            try:
                os.unlink(local_temp_path)
            except Exception:
                pass

        try:
            minio = MinioService()
            minio.remove_object(minio.bucket_temp, minio_key)
        except Exception:
            pass  # Temp bucket lifecycle will clean up eventually
```

---

## 16. Full Sync Pattern (with Deletions)

For data connections that should maintain exact parity with the source system (like CRM imports), implement full sync with deletions. Records that exist in the database but are not in the import should be deleted.

### Service Methods

Add methods to get all existing IDs and delete records not in the import:

```python
class MyDataService:
    # =========================================================================
    # FULL SYNC SUPPORT
    # =========================================================================

    async def get_all_record_ids(
        self,
        session: AsyncSession,
        organization_id: UUID,
    ) -> set[str]:
        """Get all external IDs for an organization (for full sync comparison)."""
        result = await session.execute(
            select(MyRecord.external_id).where(
                MyRecord.organization_id == organization_id
            )
        )
        return {row[0] for row in result.fetchall()}

    async def delete_records_not_in(
        self,
        session: AsyncSession,
        organization_id: UUID,
        keep_ids: set[str],
    ) -> int:
        """Delete records not in the keep set (full sync cleanup)."""
        if not keep_ids:
            return 0  # Don't delete everything if import was empty

        result = await session.execute(
            delete(MyRecord).where(
                and_(
                    MyRecord.organization_id == organization_id,
                    MyRecord.external_id.notin_(keep_ids),
                )
            )
        )
        return result.rowcount or 0
```

### Import Service Implementation

Track imported IDs and delete missing records after import:

```python
async def import_from_zip(
    self,
    session: AsyncSession,
    organization_id: UUID,
    zip_path: str,
    run_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    """Full sync import - upsert imported records, delete missing records."""

    result = {
        "records": {"created": 0, "updated": 0, "deleted": 0, "total": 0},
        "errors": [],
    }

    # Track all imported external IDs
    imported_ids: Set[str] = set()

    # Process import file
    with zipfile.ZipFile(zip_path, 'r') as zf:
        csv_file = self._find_csv(zf.namelist(), "MyRecord")
        if csv_file:
            stats, imported = await self._import_records(
                session, organization_id, zf, csv_file, run_id
            )
            result["records"]["created"] = stats["created"]
            result["records"]["updated"] = stats["updated"]
            result["records"]["total"] = stats["total"]
            imported_ids.update(imported)

    # FULL SYNC: Delete records that weren't in this import
    if imported_ids:  # Only delete if we actually imported something
        deleted = await my_data_service.delete_records_not_in(
            session, organization_id, imported_ids
        )
        result["records"]["deleted"] = deleted

        if run_id and deleted > 0:
            await run_log_service.log_event(
                session, run_id, "INFO", "full_sync_cleanup",
                f"Deleted {deleted} records not in import (full sync)"
            )

    await session.commit()
    return result


async def _import_records(
    self,
    session: AsyncSession,
    organization_id: UUID,
    zf: zipfile.ZipFile,
    filename: str,
    run_id: Optional[UUID],
) -> tuple[Dict[str, int], Set[str]]:
    """Import records, return stats and set of imported external IDs."""
    stats = {"created": 0, "updated": 0, "total": 0}
    imported_ids: Set[str] = set()

    # ... parse CSV and upsert records ...

    for row in reader:
        external_id = row.get("Id", "").strip()
        if not external_id:
            continue

        # Upsert record
        record, created = await my_data_service.upsert_record(
            session, organization_id, external_id, data
        )

        # Track imported ID
        imported_ids.add(external_id)
        stats["total"] += 1
        if created:
            stats["created"] += 1
        else:
            stats["updated"] += 1

    return stats, imported_ids
```

### Safety Considerations

1. **Don't delete if import is empty**: If no records were imported, don't delete everything. This protects against corrupt or empty import files.

2. **Log deletions**: Always log how many records were deleted for audit purposes.

3. **Consider soft deletes**: For some data, you may want to soft-delete (set `deleted_at`) instead of hard delete, allowing recovery.

4. **Cascade deletions carefully**: If deleting a parent record (e.g., Account), decide how to handle children (Contacts, Opportunities). Options:
   - Cascade delete children
   - Orphan children (set parent_id to NULL)
   - Block deletion if children exist

---

## 17. Search Integration

Data connections should be searchable through the unified search infrastructure. This requires indexing records to the `search_chunks` table and adding appropriate filters to the search UI.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           SEARCH INTEGRATION FLOW                                │
└─────────────────────────────────────────────────────────────────────────────────┘

  IMPORT/SYNC                   INDEXING                    SEARCH
       │                           │                           │
       ▼                           ▼                           ▼
┌─────────────┐            ┌─────────────────┐         ┌─────────────────┐
│ Data Import │───────────▶│ pg_index_service│────────▶│ pg_search_service│
│   Service   │            │ index_*() methods│         │ search_*() method│
└─────────────┘            └─────────────────┘         └─────────────────┘
                                   │                           │
                                   ▼                           ▼
                           ┌─────────────────┐         ┌─────────────────┐
                           │  search_chunks  │◀───────▶│  /search/{type} │
                           │     table       │         │    API endpoint │
                           └─────────────────┘         └─────────────────┘
```

### Step 1: Add Indexing Methods

**Location**: `backend/app/core/search/pg_index_service.py`

Add indexing methods for each searchable entity type:

```python
async def index_my_record(
    self,
    session: AsyncSession,
    organization_id: UUID,
    record_id: UUID,
    external_id: str,
    name: str,
    description: Optional[str] = None,
    category: Optional[str] = None,
    # ... other fields to index
) -> bool:
    """
    Index a record for search.

    Args:
        session: Database session
        organization_id: Organization UUID
        record_id: Internal record UUID
        external_id: External system ID (for reference)
        name: Record name/title
        description: Record description (for content)
        category: Classification (stored in content_type)

    Returns:
        True if indexed successfully
    """
    if not _is_search_enabled():
        return False

    try:
        # Build content for indexing (combine searchable fields)
        content_parts = [name]
        if category:
            content_parts.append(f"Category: {category}")
        if description:
            content_parts.append(description)

        content = "\n\n".join(content_parts)

        # Generate embedding for semantic search
        embedding = await embedding_service.get_embedding(content)

        # Build metadata (stored in JSONB, available for filtering)
        metadata = {
            "external_id": external_id,
            "category": category,
            # ... other filterable fields
        }

        # Delete existing chunks (handles re-indexing)
        await self._delete_chunks(session, "my_record", record_id)

        # Insert new chunk
        await self._insert_chunk(
            session=session,
            source_type="my_record",           # Unique type identifier
            source_id=record_id,
            organization_id=organization_id,
            chunk_index=0,                     # Single chunk per record
            content=content,
            title=name,
            filename=external_id,              # Displayed as secondary identifier
            url=None,                          # URL if applicable
            embedding=embedding,
            source_type_filter="my_source",    # Groups related types for filtering
            content_type=category,             # Filterable field
            metadata=metadata,
        )

        await session.commit()
        return True

    except Exception as e:
        logger.error(f"Error indexing record {record_id}: {e}")
        await session.rollback()
        return False

async def delete_my_record_index(
    self,
    session: AsyncSession,
    record_id: UUID,
) -> bool:
    """Remove record from search index."""
    try:
        await self._delete_chunks(session, "my_record", record_id)
        await session.commit()
        return True
    except Exception as e:
        logger.error(f"Failed to delete index for record {record_id}: {e}")
        return False
```

### Step 2: Call Indexing During Import

**Location**: Your import service (e.g., `backend/app/connectors/my_data/my_import_service.py`)

Add indexing after successful import:

```python
async def import_data(self, session, organization_id, data_source, run_id=None):
    """Import data and index for search."""

    # ... import logic ...

    # After successful import, index records for search
    if run_id:
        await run_log_service.log_event(
            session, run_id, "INFO", "indexing",
            "Indexing records for search"
        )

    indexed_count = 0
    for record in imported_records:
        try:
            success = await pg_index_service.index_my_record(
                session=session,
                organization_id=organization_id,
                record_id=record.id,
                external_id=record.external_id,
                name=record.name,
                description=record.description,
                category=record.category,
            )
            if success:
                indexed_count += 1
        except Exception as e:
            logger.warning(f"Failed to index record {record.id}: {e}")

    logger.info(f"Indexed {indexed_count} records for search")
    return {"imported": len(imported_records), "indexed": indexed_count}
```

### Step 3: Add Search Service Method

**Location**: `backend/app/core/search/pg_search_service.py`

Add a search method for your data type:

```python
async def search_my_data(
    self,
    session: AsyncSession,
    organization_id: UUID,
    query: str,
    entity_types: Optional[List[str]] = None,  # Filter by type
    categories: Optional[List[str]] = None,     # Filter by category
    limit: int = 20,
    offset: int = 0,
) -> SearchResults:
    """
    Search my data records.

    Args:
        session: Database session
        organization_id: Organization UUID
        query: Search query
        entity_types: Filter by entity type (type_a, type_b, etc.)
        categories: Filter by category
        limit: Maximum results
        offset: Pagination offset

    Returns:
        SearchResults with matching records
    """
    try:
        filters = ["sc.organization_id = :org_id"]
        params: Dict[str, Any] = {"org_id": str(organization_id)}

        # Filter by source types
        if entity_types:
            source_types = [f"my_{et}" for et in entity_types]  # Map to source_type values
            filters.append("sc.source_type = ANY(:source_types)")
            params["source_types"] = source_types
        else:
            # Default: search all entity types
            filters.append("sc.source_type IN ('my_type_a', 'my_type_b')")

        # Filter by category (stored in content_type or metadata)
        if categories:
            filters.append("sc.content_type = ANY(:categories)")
            params["categories"] = categories

        filter_clause = " AND ".join(filters)

        # Escape query for full-text search
        fts_query = self._escape_fts_query(query)
        if not fts_query:
            return SearchResults(total=0, hits=[])

        params["fts_query"] = fts_query

        # Execute search (similar to search_sam pattern)
        # ... SQL query with ranking, highlighting, pagination ...

        return SearchResults(total=total, hits=hits)

    except Exception as e:
        logger.error(f"Search failed: {e}")
        return SearchResults(total=0, hits=[])
```

### Step 4: Add Search API Endpoint

**Location**: `backend/app/api/v1/data/routers/search.py`

Add request model and endpoints:

```python
class MyDataSearchRequest(BaseModel):
    """Search request for my data."""

    query: str = Field(..., min_length=1, max_length=500)
    entity_types: Optional[List[str]] = Field(None, description="Filter by type")
    categories: Optional[List[str]] = Field(None, description="Filter by category")
    limit: int = Field(20, ge=1, le=100)
    offset: int = Field(0, ge=0)


@router.post(
    "/my_data",
    response_model=SearchResponse,
    summary="Search my data",
    description="Full-text search across my data records.",
)
async def search_my_data(
    request: MyDataSearchRequest,
    current_user: User = Depends(get_current_user),
) -> SearchResponse:
    """Search my data records."""
    if not _is_search_enabled():
        raise HTTPException(status_code=503, detail="Search not enabled")

    async with database_service.get_session() as session:
        results = await pg_search_service.search_my_data(
            session=session,
            organization_id=current_user.organization_id,
            query=request.query,
            entity_types=request.entity_types,
            categories=request.categories,
            limit=request.limit,
            offset=request.offset,
        )

    return SearchResponse(
        total=results.total,
        limit=request.limit,
        offset=request.offset,
        query=request.query,
        hits=[
            SearchHitResponse(
                asset_id=hit.asset_id,
                score=hit.score,
                title=hit.title,
                filename=hit.filename,
                source_type=hit.source_type,  # Display-friendly label
                content_type=hit.content_type,
                highlights=hit.highlights,
            )
            for hit in results.hits
        ],
    )


@router.get("/my_data", response_model=SearchResponse)
async def search_my_data_get(
    q: str = Query(..., min_length=1, max_length=500),
    entity_types: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
) -> SearchResponse:
    """GET endpoint for search."""
    # Parse comma-separated filters and call search_my_data
    ...
```

### Step 5: Update Frontend Search Page

**Location**: `frontend/app/search/page.tsx`

Add your source type to the filter configuration:

```typescript
import { MyIcon } from 'lucide-react'  // Or appropriate icon

// Add to sourceTypeConfig
const sourceTypeConfig: Record<string, { name: string; icon: React.ReactNode; color: string }> = {
  // ... existing types ...
  my_source: {
    name: 'My Data',
    icon: <MyIcon className="w-4 h-4" />,
    color: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  },
}
```

Update the help text:
```typescript
<p className="text-gray-500">
  Search across uploads, SharePoint, web scrapes, SAM.gov, Salesforce, and My Data.
</p>
```

### Key Fields in search_chunks Table

| Field | Purpose | Example |
|-------|---------|---------|
| `source_type` | Unique identifier for record type | "salesforce_account", "sam_notice" |
| `source_id` | UUID of the record | Account UUID |
| `source_type_filter` | Groups related types for UI filtering | "salesforce" groups account/contact/opportunity |
| `content` | Searchable text content | Name + description + category |
| `title` | Display title | Account name |
| `filename` | Secondary identifier | Salesforce ID |
| `content_type` | Filterable category | Account type, stage name |
| `embedding` | Vector for semantic search | 1536-dim embedding |
| `metadata` | JSONB for additional filterable fields | {"industry": "Tech", "stage": "Closed"} |

### Display Labels

When returning search results, map `source_type` to user-friendly labels:

```python
# In search method
display_type = row.source_type
if row.source_type == "salesforce_account":
    display_type = "Account"
elif row.source_type == "salesforce_contact":
    display_type = "Contact"
elif row.source_type == "salesforce_opportunity":
    display_type = "Opportunity"
```

This allows the frontend to display clear labels like "Account" instead of "salesforce_account".

### Grouped Entity Types in Unified Search

When your data connection has multiple entity types that should be grouped for filtering (e.g., Salesforce has Account, Contact, Opportunity), you need to:

1. **Set `source_type_filter` to the group name** when indexing:
```python
# In pg_index_service.py
await self._insert_chunk(
    source_type="salesforce_account",    # Specific entity type
    source_type_filter="salesforce",     # Group name for filter
    # ...
)
```

2. **Update the main search method** in `pg_search_service.py` to handle the group:
```python
# In the search() method filter handling
if source_types and "salesforce" in source_types:
    # Search Salesforce records
    other_types = [t for t in source_types if t != "salesforce"]
    if other_types:
        # Mixed search: Salesforce + other sources
        filters.append("""(
            sc.source_type IN ('salesforce_account', 'salesforce_contact', 'salesforce_opportunity')
            OR (sc.source_type = 'asset' AND sc.source_type_filter = ANY(:asset_source_types))
        )""")
        params["asset_source_types"] = other_types
    else:
        filters.append("sc.source_type IN ('salesforce_account', 'salesforce_contact', 'salesforce_opportunity')")
```

3. **Return both `source_type` and `source_type_filter`** in SQL, then map to display labels:
```python
# In SQL query
SELECT source_type, source_type_filter, ...

# In result processing
display_source_type = row.source_type_filter
if row.source_type == "salesforce_account":
    display_source_type = "Account"
elif row.source_type == "salesforce_contact":
    display_source_type = "Contact"
```

4. **Add entries in frontend `sourceTypeConfig`** for both filter and result labels:
```typescript
// For filter button
salesforce: {
  name: 'Salesforce',
  icon: <Database className="w-4 h-4" />,
  color: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400',
},
// For result labels (returned from API)
Account: {
  name: 'SF Account',
  icon: <Building2 className="w-4 h-4" />,
  color: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400',
},
Contact: {
  name: 'SF Contact',
  icon: <User className="w-4 h-4" />,
  color: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-400',
},
```

5. **Route search result clicks** to appropriate detail pages:
```typescript
const handleResultClick = (hit: SearchHit) => {
  if (hit.source_type === 'Account') {
    router.push(`/salesforce/accounts/${hit.asset_id}`)
  } else if (hit.source_type === 'Contact') {
    router.push(`/salesforce/contacts/${hit.asset_id}`)
  } else if (hit.source_type === 'Opportunity') {
    router.push(`/salesforce/opportunities/${hit.asset_id}`)
  } else {
    router.push(`/assets/${hit.asset_id}`)
  }
}
```

### Checklist for Search Integration

- [ ] Add indexing methods to `pg_index_service.py`
- [ ] Add delete index methods
- [ ] Call indexing during import/sync
- [ ] Add search method to `pg_search_service.py` (for dedicated `/search/{type}` endpoint)
- [ ] Update main `search()` method to handle source type filter (for unified search)
- [ ] Update `search_with_facets()` to include new source in facet counts
- [ ] Map source_type to display-friendly labels in search result processing
- [ ] Add search API endpoint (POST and GET)
- [ ] Add source type to frontend filter config (`sourceTypeConfig`)
- [ ] Add entity type labels to frontend config (for grouped types like Account/Contact/Opportunity)
- [ ] Update frontend `handleResultClick` to route to appropriate detail pages
- [ ] Update frontend help text
- [ ] Test search with sample data
- [ ] Verify facet counts appear correctly
- [ ] Verify result labels show correctly (Account vs salesforce_account)

---

## 18. Adapter System

When your data connection calls external APIs, implement the **3-tier configuration resolution** pattern using the `ServiceAdapter` base class.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        3-TIER CONFIG RESOLUTION                                  │
└─────────────────────────────────────────────────────────────────────────────────┘

  Tier 1 (Highest Priority)       Tier 2                      Tier 3 (Fallback)
  Per-Organization DB              config.yml Section           Environment Variables
       │                               │                            │
       ▼                               ▼                            ▼
┌─────────────────┐           ┌─────────────────┐          ┌─────────────────┐
│ connections     │           │ config.yml      │          │ settings.*      │
│ table           │           │ my_source:      │          │ MY_SOURCE_KEY   │
│ (connection_    │           │   api_key: xxx  │          │ MY_SOURCE_URL   │
│  service)       │           │   base_url: ... │          │                 │
└─────────────────┘           └─────────────────┘          └─────────────────┘
       │                               │                            │
       └───────────────┬───────────────┘────────────────────────────┘
                       ▼
              Merged Configuration
              (first non-null wins)
```

### ServiceAdapter ABC

**Location**: `backend/app/connectors/adapters/base.py`

```python
from app.connectors.adapters.base import ServiceAdapter

class MySourceAdapter(ServiceAdapter):
    """Adapter for My Source API with 3-tier config resolution."""

    CONNECTION_TYPE = "my_source"  # Must match registered connection type

    def __init__(self, api_key=None, base_url=None, **kwargs):
        # Tier 3: Environment variable fallback
        from app.config import settings
        self.api_key = api_key or settings.my_source_api_key
        self.base_url = base_url or settings.my_source_base_url or "https://api.mysource.com"

    @classmethod
    async def from_database(cls, organization_id, session):
        """Factory: creates adapter with Tier 1 (DB) config."""
        connection = await cls._get_db_connection(organization_id, session)
        if connection:
            config = connection.config or {}
            return cls(
                api_key=config.get("api_key"),
                base_url=config.get("base_url"),
            )
        return cls()  # Falls back to Tier 2/3

    async def resolve_config(self) -> dict:
        """Resolve config from Tiers 2+3 (no DB)."""
        return {"api_key": self.api_key, "base_url": self.base_url}

    async def resolve_config_for_org(self, organization_id, session) -> dict:
        """Resolve config with Tier 1 (DB) as highest priority."""
        connection = await self._get_db_connection(organization_id, session)
        if connection and connection.config:
            return {**await self.resolve_config(), **connection.config}
        return await self.resolve_config()

    async def test_connection(self) -> dict:
        """Test API connectivity."""
        try:
            # Call a lightweight endpoint
            response = await self._client.get(f"{self.base_url}/health")
            return {"success": True, "message": "Connected"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @property
    def is_available(self) -> bool:
        return bool(self.api_key)


# Module-level singleton
my_source_adapter = MySourceAdapter()
```

### Existing Adapter Implementations

| Adapter | Connection Type | File |
|---------|----------------|------|
| `PlaywrightClient` | `"playwright"` | `backend/app/connectors/adapters/playwright_adapter.py` |
| `LLMAdapter` | `"llm"` | `backend/app/connectors/adapters/llm_adapter.py` |

### Inline Config Resolution (Alternative)

Some connectors implement config resolution inline rather than subclassing `ServiceAdapter`:

```python
# In your pull service
async def _get_api_key_async(self, organization_id, session):
    """3-tier config resolution without adapter subclass."""
    # Tier 1: Instance override
    if self._api_key:
        return self._api_key

    # Tier 2: Database connection
    from app.core.auth.connection_service import connection_service
    conn = await connection_service.get_default_connection(
        session, organization_id, "my_source"
    )
    if conn and conn.config and conn.config.get("api_key"):
        return conn.config["api_key"]

    # Tier 3: Environment variable
    from app.config import settings
    return settings.my_source_api_key
```

This pattern is used by: SAM.gov (`sam_pull_service.py`), SharePoint (`sharepoint_service.py`), Salesforce.

---

## 19. Connector Service Standards

All connectors follow consistent patterns. This section documents the standards that every new connector should follow.

### File Organization

```
backend/app/connectors/{name}/
├── __init__.py
├── {name}_service.py          # CRUD service (database operations)
├── {name}_pull_service.py     # Data ingestion from external APIs
├── {name}_import_service.py   # Data import from files (alternative to pull)
└── {name}_client.py           # API client (optional, for complex APIs)
```

### CRUD Service Pattern

```python
"""
My Source service for Curatore v2.
Provides CRUD operations for My Source records.
"""
import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database.models import MySourceRecord

logger = logging.getLogger("curatore.connectors.my_source")


class MySourceService:
    """CRUD operations for My Source records."""

    # =========================================================================
    # UPSERT OPERATIONS (by external ID)
    # =========================================================================

    async def upsert_record(
        self,
        session: AsyncSession,
        organization_id: UUID,
        external_id: str,
        data: Dict[str, Any],
    ) -> Tuple[MySourceRecord, bool]:
        """
        Create or update a record by external ID.
        Returns (record, was_created).
        """
        result = await session.execute(
            select(MySourceRecord).where(
                and_(
                    MySourceRecord.organization_id == organization_id,
                    MySourceRecord.external_id == external_id,
                )
            )
        )
        record = result.scalar_one_or_none()

        if record:
            for key, value in data.items():
                if hasattr(record, key):
                    setattr(record, key, value)
            return record, False
        else:
            record = MySourceRecord(
                organization_id=organization_id,
                external_id=external_id,
                **data,
            )
            session.add(record)
            return record, True

    # =========================================================================
    # READ OPERATIONS (always scoped to organization_id)
    # =========================================================================

    async def list_records(
        self,
        session: AsyncSession,
        organization_id: UUID,
        keyword: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[MySourceRecord], int]:
        """List with filtering and pagination. Returns (items, total_count)."""
        query = select(MySourceRecord).where(
            MySourceRecord.organization_id == organization_id
        )
        if keyword:
            query = query.where(MySourceRecord.name.ilike(f"%{keyword}%"))

        count_query = select(func.count()).select_from(query.subquery())
        total = (await session.execute(count_query)).scalar() or 0

        query = query.order_by(MySourceRecord.name).limit(limit).offset(offset)
        result = await session.execute(query)
        return list(result.scalars().all()), total


# Singleton instance
my_source_service = MySourceService()
```

### Pull Service Pattern

```python
"""
My Source pull service — orchestrates data ingestion from external API.
"""
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.shared.run_service import run_service
from app.core.shared.run_log_service import run_log_service
from app.core.search.pg_index_service import pg_index_service

logger = logging.getLogger("curatore.connectors.my_source.pull")

# Transient errors that should trigger retry
TRANSIENT_ERRORS = (ConnectionError, TimeoutError, OSError)


class MySourcePullService:
    """Orchestrates data pull from My Source API."""

    async def pull(
        self,
        session: AsyncSession,
        organization_id: UUID,
        config: Dict[str, Any],
        run_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        """
        Pull data from external API.
        Returns stats dict: {created, updated, deleted, errors}.
        """
        stats = {"created": 0, "updated": 0, "errors": 0}

        # 1. Check if run was cancelled
        if run_id and await self._is_run_cancelled(session, run_id):
            return stats

        # 2. Log progress
        if run_id:
            await run_log_service.log_event(
                session, run_id, "INFO", "pull_start",
                "Starting data pull"
            )

        # 3. Fetch data with retry
        try:
            data = await self._fetch_with_retry(config)
        except Exception as e:
            if run_id:
                await run_log_service.log_event(
                    session, run_id, "ERROR", "api_error", str(e)
                )
            raise

        # 4. Process records
        for item in data:
            try:
                record, created = await my_source_service.upsert_record(
                    session, organization_id, item["id"], item
                )
                stats["created" if created else "updated"] += 1

                # 5. Index for search
                await pg_index_service.index_my_record(session, record)

            except Exception as e:
                stats["errors"] += 1
                logger.warning(f"Error processing record: {e}")

            # 6. Periodic cancellation check
            if run_id and stats["created"] % 50 == 0:
                if await self._is_run_cancelled(session, run_id):
                    break

        return stats

    async def _fetch_with_retry(self, config, max_retries=3):
        """Fetch data with exponential backoff for transient errors."""
        import asyncio
        for attempt in range(max_retries):
            try:
                return await self._fetch_data(config)
            except TRANSIENT_ERRORS as e:
                if attempt == max_retries - 1:
                    raise
                wait = 2 ** attempt
                logger.warning(f"Transient error, retrying in {wait}s: {e}")
                await asyncio.sleep(wait)

    async def _is_run_cancelled(self, session, run_id):
        """Check if the run has been cancelled for graceful stops."""
        run = await run_service.get_run(session, run_id)
        return run and run.status in ("cancelled", "cancelling")


my_source_pull_service = MySourcePullService()
```

### Common Patterns Across All Connectors

| Pattern | Description | Used By |
|---------|-------------|---------|
| **Organization isolation** | Every query includes `organization_id` filter | All connectors |
| **Singleton instances** | `service = MyService()` at module bottom | All connectors |
| **Upsert by external ID** | `(org_id, external_id)` unique constraint | SAM, Salesforce, Forecasts |
| **Pagination tuple** | `(List[T], total_count)` return pattern | All CRUD services |
| **Run log integration** | `run_log_service.log_event()` during ingestion | All pull/import services |
| **Cancellation checks** | `_is_run_cancelled()` during long operations | SAM, SharePoint, Scrape |
| **Retry with backoff** | Exponential backoff for `TRANSIENT_ERRORS` | SAM, SharePoint |
| **Slug generation** | URL-friendly identifiers for configs | SAM searches, SharePoint configs |
| **Source metadata** | Connectors write namespaced `Asset.source_metadata` | SharePoint, SAM, Scrape |
| **Status tracking** | `status`, `last_sync_at`, `last_sync_run_id` on config models | All sync configs |

### Source Metadata Convention

When creating Assets, write fully namespaced `source_metadata`:

```python
source_metadata = {
    "source": {
        "storage_folder": "my_source/records/",
    },
    "my_source": {
        "item_id": "ext-123",
        "record_type": "report",
        "category": "financial",
        # ... connector-specific fields
    },
    "sync": {
        "config_id": str(config.id),
        "config_name": config.name,
    },
    "file": {
        "extension": ".pdf",
        "description": "Financial report Q1 2026",
    },
}

asset = await asset_service.create_asset(
    session=session,
    organization_id=organization_id,
    source_type="my_source",
    source_metadata=source_metadata,
    # ...
)
```

This metadata flows through `AssetPassthroughBuilder` into search chunks automatically.

---

## 20. Metadata Registry System

The metadata registry governs field definitions, facets, namespaces, data source knowledge, and reference data. All baseline definitions live in YAML files under `backend/app/core/metadata/registry/`. Organization-level overrides are stored in the database.

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           METADATA REGISTRY FLOW                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

  YAML Baseline                  DB Overrides               Effective Registry
       │                              │                           │
       ▼                              ▼                           ▼
┌─────────────────┐          ┌─────────────────┐         ┌─────────────────┐
│ namespaces.yaml │          │ metadata_field_ │         │ MetadataRegistry│
│ fields.yaml     │──seed──▶ │ definitions     │──merge─▶│ Service         │
│ facets.yaml     │  (DB)    │ facet_defs      │  (5min  │ (cached result) │
│ data_sources.yaml│         │ facet_mappings  │  cache) │                 │
│ reference_data.  │         └─────────────────┘         └─────────────────┘
│  yaml            │                                            │
└─────────────────┘                                            ▼
                                                    ┌─────────────────────┐
                                                    │ Search / Functions  │
                                                    │ / Procedure Gen     │
                                                    └─────────────────────┘
```

### Namespaces (`registry/namespaces.yaml`)

Namespaces organize metadata fields by domain. Each namespace has a `key`, `display_name`, and `description`.

```yaml
namespaces:
  - key: source
    display_name: Source
    description: Common provenance fields across all content types

  - key: my_source
    display_name: My Source
    description: Fields specific to My Source integration

  # Existing namespaces: source, sharepoint, sam, salesforce, forecast, scrape, sync, file, custom
```

**When to add a namespace**: When your connector has fields that don't fit in existing namespaces. Most connectors need their own namespace.

### Fields (`registry/fields.yaml`)

Field definitions describe every metadata field. Used by the catalog API, search schema discovery, and validation.

```yaml
fields:
  # Existing fields in other namespaces...

  # My Source fields
  - key: my_source.record_type
    display_name: Record Type
    namespace: my_source
    data_type: enum
    indexed: true
    facetable: true
    description: Type of record in My Source
    applicable_content_types:
      - my_source_record
    examples:
      - report
      - analysis
      - memo

  - key: my_source.category
    display_name: Category
    namespace: my_source
    data_type: string
    indexed: true
    facetable: true
    description: Record category
    applicable_content_types:
      - my_source_record

  - key: my_source.external_id
    display_name: External ID
    namespace: my_source
    data_type: string
    indexed: true
    facetable: false
    description: External system identifier
    applicable_content_types:
      - my_source_record
```

**Field properties:**

| Property | Type | Description |
|----------|------|-------------|
| `key` | `str` | Unique key in `namespace.field_name` format |
| `display_name` | `str` | Human-friendly label |
| `namespace` | `str` | Must match a namespace key |
| `data_type` | `str` | `string`, `number`, `boolean`, `date`, `enum`, `array`, `object` |
| `indexed` | `bool` | Whether stored in `search_chunks.metadata` |
| `facetable` | `bool` | Whether usable as a facet filter |
| `description` | `str` | Human-readable description |
| `applicable_content_types` | `List[str]` | Content types this field appears on |
| `examples` | `List` | Example values |

### Facets (`registry/facets.yaml`)

Facets are **cross-domain filters** that map to different JSON paths depending on content type. This is the key abstraction that lets a single filter like `{"agency": "GSA"}` work across SAM notices, forecasts, and Salesforce records.

```yaml
facets:
  # Existing facets: agency, naics_code, set_aside, site_name, etc.

  - key: my_category
    display_name: My Category
    description: Category filter across My Source records
    data_type: string
    operators:
      - eq    # Exact match
      - in    # Match any of list
    mappings:
      - content_type: my_source_record
        json_path: my_source.category
```

**How facet resolution works:**

1. User passes `facet_filters={"agency": "GSA"}` to a search function
2. `MetadataRegistryService.resolve_facet("agency")` returns mappings per content type
3. Search service builds content-type-specific JSONB queries:
   - SAM notices: `metadata->'sam'->>'agency' = 'GSA'`
   - Forecasts: `metadata->'forecast'->>'agency_name' = 'GSA'`
   - Salesforce: `metadata->'salesforce'->>'account_name' = 'GSA'`

**Facet operators:**

| Operator | Description | Example |
|----------|-------------|---------|
| `eq` | Exact match | `{"agency": "GSA"}` |
| `in` | Match any value in list | `{"agency": ["GSA", "DOD"]}` |
| `gte` | Greater than or equal | `{"fiscal_year": {"gte": 2026}}` |
| `lte` | Less than or equal | `{"estimated_value": {"lte": 1000000}}` |
| `contains` | Substring match | `{"description": {"contains": "cloud"}}` |
| `exists` | Field is not null | `{"naics_code": {"exists": true}}` |

### Data Sources (`registry/data_sources.yaml`)

Data source definitions tell the AI procedure generator and `discover_data_sources` function about available data types, their capabilities, and which CWR functions to use.

```yaml
data_sources:
  # Existing: sam_gov, sharepoint, forecast_ag, forecast_apfs, forecast_state, salesforce, web_scrape

  my_source:
    display_name: My Source
    description: >
      My Source provides research reports, analysis documents, and memos.
      Records are synced periodically and indexed for search.
    data_contains:
      - Research reports
      - Analysis documents
      - Internal memos
    capabilities:
      - full_text_search
      - facet_filtering
      - semantic_search
    search_tools:
      - tool: search_my_source
        description: Search My Source records
        filters:
          - record_type (enum: report, analysis, memo)
          - category
          - facet_filters (cross-domain facets)
        next_steps:
          - Use get_content(asset_ids=[...]) to read full document text
          - Use get(item_type="my_source_record", item_id="...") for record details
    example_questions:
      - "Find all reports about cloud migration"
      - "What analysis documents mention cybersecurity?"
      - "Show me memos from Q1 2026"
    note: >
      My Source data is org-specific. Use discover_data_sources to see what
      is configured for the current organization.
```

**Key fields:**

| Field | Description |
|-------|-------------|
| `display_name` | Human-friendly name |
| `description` | What this data source contains |
| `data_contains` | List of content types in plain English |
| `capabilities` | What you can do with this data |
| `search_tools` | CWR functions to use, with filter descriptions and next steps |
| `example_questions` | Natural language queries the AI can answer |
| `note` | Important caveats (org-specific, rate limits, etc.) |

### Reference Data (`registry/reference_data.yaml`)

Reference data provides canonical values and aliases for facets, enabling cross-source matching. For example, "DHS" should match "HOMELAND SECURITY, DEPARTMENT OF" across SAM.gov and forecasts.

```yaml
reference_data:
  agency:
    description: Federal agency canonical names and aliases
    entries:
      - canonical: "GENERAL SERVICES ADMINISTRATION"
        aliases: ["GSA", "General Services Administration"]
        category: civilian

      - canonical: "HOMELAND SECURITY, DEPARTMENT OF"
        aliases: ["DHS", "Department of Homeland Security"]
        category: civilian

      # Add entries for agencies your data source uses
      - canonical: "MY AGENCY NAME"
        aliases: ["MA", "My Agency"]
        category: civilian
```

**How reference data works:**

1. `FacetReferenceService` loads entries at startup
2. When a user searches for `agency: "DHS"`, the service resolves it to all aliases
3. The search query expands to match "DHS", "HOMELAND SECURITY, DEPARTMENT OF", etc.
4. `autocomplete()` provides prefix-based suggestions
5. `discover_unmapped()` finds values in search chunks not yet in reference data

### MetadataRegistryService

**Location**: `backend/app/core/metadata/registry_service.py`

Key methods:

| Method | Description |
|--------|-------------|
| `load_baseline()` | Seed DB from YAML files (DELETE + INSERT global records) |
| `get_effective_registry(org_id)` | Merge global + org-level overrides (5-min cache) |
| `get_namespace_definitions()` | All namespace definitions |
| `get_field_definitions(namespace)` | Field definitions, optionally filtered by namespace |
| `get_facet_definitions()` | All facet definitions with mappings |
| `resolve_facet(facet_name)` | Returns `{content_type: json_path}` mapping |
| `get_field_stats(org_id)` | Sample values and document counts per field |

### Validation Service

**Location**: `backend/app/core/metadata/validation_service.py`

Validates at startup:
1. Builder fields exist in YAML field definitions
2. YAML fields with `applicable_content_types` have corresponding builders
3. Facet mapping JSON paths are valid

---

## 21. Metadata Builders

Metadata builders transform connector data into the namespaced JSONB structure stored in `search_chunks.metadata`. This is the bridge between your connector's data model and the search/facet infrastructure.

### Architecture

```
Connector writes Asset.source_metadata     OR      Connector indexes entity directly
          │                                                    │
          ▼                                                    ▼
┌─────────────────────────┐                     ┌─────────────────────────┐
│ AssetPassthroughBuilder │                     │ EntityMetadataBuilder   │
│ (passes metadata thru)  │                     │ (builds from columns)   │
└─────────────────────────┘                     └─────────────────────────┘
          │                                                    │
          └────────────────────┬───────────────────────────────┘
                               ▼
                   ┌───────────────────────┐
                   │ search_chunks.metadata │
                   │ (namespaced JSONB)     │
                   └───────────────────────┘
```

### Two Builder Strategies

**Strategy 1: Asset Pass-through** — Your connector creates `Asset` records with namespaced `source_metadata`. The `AssetPassthroughBuilder` copies it to search chunks unchanged. Used when your data is document-centric (SharePoint files, scraped pages, SAM attachments).

**Strategy 2: Entity Builder** — Your connector has its own database tables (not Assets). Create a custom `MetadataBuilder` subclass that reads model columns and builds namespaced metadata. Used for structured records (SAM solicitations, forecasts, Salesforce records).

### Creating an Entity Builder

**Location**: `backend/app/core/search/metadata_builders.py`

```python
from .metadata_builders import MetadataBuilder, metadata_builder_registry


class MySourceRecordBuilder(MetadataBuilder):
    """Build search metadata from My Source records."""

    source_type = "my_source_record"
    namespace = "my_source"

    def build_content(self, **kwargs) -> str:
        """
        Build indexable text content from record fields.
        This text is used for full-text and semantic search.
        """
        parts = []
        if kwargs.get("name"):
            parts.append(kwargs["name"])
        if kwargs.get("category"):
            parts.append(f"Category: {kwargs['category']}")
        if kwargs.get("description"):
            parts.append(kwargs["description"])
        return "\n\n".join(parts)

    def build_metadata(self, **kwargs) -> dict:
        """
        Build namespaced JSONB metadata for search_chunks.metadata.
        Fields here must match what's declared in fields.yaml.
        """
        return {
            self.namespace: {
                "external_id": kwargs.get("external_id"),
                "record_type": kwargs.get("record_type"),
                "category": kwargs.get("category"),
            }
        }

    def get_schema(self) -> dict:
        """Returns {namespace: [field_names]} for validation."""
        return {
            self.namespace: ["external_id", "record_type", "category"]
        }
```

### Register the Builder

In `_register_defaults()` at the bottom of `metadata_builders.py`:

```python
def _register_defaults(self):
    # ... existing builders ...
    self.register(MySourceRecordBuilder())
```

### Using the Builder in PgIndexService

**Location**: `backend/app/core/search/pg_index_service.py`

Add an indexing method:

```python
async def index_my_source_record(
    self,
    session: AsyncSession,
    record: MySourceRecord,
) -> bool:
    """Index a My Source record for search."""
    builder = metadata_builder_registry.get("my_source_record")
    if not builder:
        logger.warning("No builder for my_source_record")
        return False

    try:
        # Build content and metadata using the builder
        content = builder.build_content(
            name=record.name,
            category=record.category,
            description=record.description,
        )
        metadata = builder.build_metadata(
            external_id=record.external_id,
            record_type=record.record_type,
            category=record.category,
        )

        # Generate embedding for semantic search
        embedding = await self._get_embedding(content)

        # Delete existing chunks and insert new
        await self._delete_chunks(session, "my_source_record", record.id)
        await self._insert_chunk(
            session=session,
            source_type="my_source_record",
            source_id=record.id,
            organization_id=record.organization_id,
            chunk_index=0,
            content=content,
            title=record.name,
            filename=record.external_id,
            embedding=embedding,
            source_type_filter="my_source",
            content_type=record.record_type,
            metadata=metadata,
        )

        record.indexed_at = datetime.utcnow()
        return True

    except Exception as e:
        logger.error(f"Error indexing record {record.id}: {e}")
        return False
```

### Existing Builders Reference

| Builder | Source Type | Namespace | Strategy |
|---------|-----------|-----------|----------|
| `AssetPassthroughBuilder` | `asset_*` | (pass-through) | Asset pass-through |
| `SamNoticeBuilder` | `sam_notice` | `sam` | Entity builder |
| `SamSolicitationBuilder` | `sam_solicitation` | `sam` | Entity builder |
| `ForecastBuilder` | `*_forecast` | `forecast` | Entity builder |
| `SalesforceAccountBuilder` | `salesforce_account` | `salesforce` | Entity builder |
| `SalesforceContactBuilder` | `salesforce_contact` | `salesforce` | Entity builder |
| `SalesforceOpportunityBuilder` | `salesforce_opportunity` | `salesforce` | Entity builder |

### End-to-End Integration Checklist

| Step | File | What to Do |
|------|------|------------|
| 1 | `registry/namespaces.yaml` | Add your namespace |
| 2 | `registry/fields.yaml` | Add field definitions with `indexed`, `facetable`, `applicable_content_types` |
| 3 | `registry/facets.yaml` | Add or extend facets with mappings to your namespace |
| 4 | `registry/data_sources.yaml` | Add data source entry with search tools and example questions |
| 5 | `registry/reference_data.yaml` | Add canonical values/aliases for your facets (if applicable) |
| 6 | `metadata_builders.py` | Create builder subclass + register in `_register_defaults()` |
| 7 | `pg_index_service.py` | Add `index_my_source_record()` method using your builder |
| 8 | Your pull/import service | Call `pg_index_service.index_my_source_record()` after data ingestion |
