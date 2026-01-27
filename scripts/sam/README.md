# SAM.gov Integration Scripts

Scripts for pulling data from SAM.gov (System for Award Management) API and storing in Curatore with AI-powered analysis.

---

## Overview

The SAM.gov integration automatically fetches government contracting opportunities for DHS agencies, filters by target NAICS codes, downloads attachments, generates AI-powered intelligence summaries, and stores everything in object storage with full database tracking.

**Target Agencies:**
- U.S. Immigration and Customs Enforcement (ICE)
- U.S. Customs and Border Protection (CBP)
- U.S. Citizenship and Immigration Services (USCIS)

**Notice Types:**
- Sources Sought (RFIs)
- Special Notice (Industry Days)
- Solicitation
- Combined Synopsis/Solicitation

**NAICS Code Filtering:**
- 541511 (Custom Computer Programming Services)
- 541512 (Computer Systems Design Services)
- 541519 (Other Computer Related Services)
- 518210 (Data Processing, Hosting, and Related Services)
- 541513 (Computer Facilities Management Services)
- 541611 (Administrative Management and General Management Consulting Services)
- 541618 (Other Management Consulting Services)
- 541690 (Other Scientific and Technical Consulting Services)
- 541330 (Engineering Services)

---

## Scripts

### sam_pull.py

**Intelligent SAM.gov opportunity aggregation and analysis**

Fetches opportunities from SAM.gov, filters by NAICS codes, downloads attachments, fetches full descriptions, generates AI-powered intelligence briefs, and stores everything in organized object storage with database tracking.

**What It Does:**
1. Fetches opportunities from last 7 days (configurable)
2. Filters for DHS agencies and target NAICS codes
3. Downloads resource files (PDFs, DOCs, etc.) for matched opportunities
4. Fetches full descriptions from SAM.gov API
5. Generates AI-powered daily intelligence brief (Markdown + PDF)
6. Uploads all files to MinIO with database artifact tracking
7. Handles timeouts and API errors with automatic retry logic

**Storage Structure:**
```
curatore-uploads/{org_id}/sam/
├── daily_extract/
│   └── sam_pull_20260127.json           # Consolidated JSON with all opportunities
├── daily_extract_summary/
│   ├── sam_pull_summary_20260127.md     # AI-generated intelligence brief (Markdown)
│   └── sam_pull_summary_20260127.pdf    # AI-generated intelligence brief (PDF)
└── {solicitationNumber}/
    └── [resource files]                  # Downloaded attachments (PDFs, DOCs, etc.)
```

**Database:** All files tracked in Artifact table for frontend visibility

**Quick Start:**

```bash
# 1. Ensure services are running
cd /path/to/curatore-v2
./scripts/dev-up.sh
./scripts/init_storage.sh

# 2. Configure .env (one-time)
SAM_API_KEY=your-sam-gov-api-key
DEFAULT_ORG_ID=your-org-uuid

# 3. Run the script (EASIEST - handles everything automatically)
./scripts/sam/run.sh

# Alternative methods:
# Via Docker
docker-compose exec backend python /app/scripts/sam/sam_pull.py

# Via backend virtual environment
cd backend && source venv/bin/activate && cd ..
python scripts/sam/sam_pull.py
```

**Get SAM.gov API Key:**
1. Register at https://sam.gov/
2. Navigate to: Data Services → API Access
3. Generate API key
4. Add to `.env`: `SAM_API_KEY=your-key-here`

**View Results:**
- **Frontend:** http://localhost:3000/storage → Default Storage → {org_id} → sam/
  - `daily_extract/` - JSON data files
  - `daily_extract_summary/` - AI-powered reports (Markdown + PDF)
  - `{solicitationNumber}/` - Downloaded attachments
- **MinIO Console:** http://localhost:9001 (login: admin/changeme)

**Schedule Daily Runs:**

Using Docker (recommended):
```bash
crontab -e
# Add:
0 6 * * * cd /path/to/curatore-v2 && docker-compose exec -T backend python /app/scripts/sam/sam_pull.py >> logs/sam_pull.log 2>&1
```

Using virtual environment:
```bash
crontab -e
# Add:
0 6 * * * cd /path/to/curatore-v2 && source backend/venv/bin/activate && python scripts/sam/sam_pull.py >> logs/sam_pull.log 2>&1
```

**Output Format (JSON):**
```json
{
  "metadata": {
    "pulled_at_utc": "2026-01-27T12:00:00.000000",
    "source": "SAM.gov Opportunities API",
    "date": "01/20/2026",
    "record_count": 25,
    "naics_matched_count": 5,
    "target_naics_codes": ["541511", "541512", ...]
  },
  "opportunities": [
    {
      "noticeId": "abc123",
      "solicitationNumber": "70ABC123456",
      "title": "Software Development Services",
      "_naics_match": true,
      "_full_description": { ... },
      "resourceLinks": [...],
      "_errors": []
    }
  ]
}
```

**Output Format (AI Summary - Markdown/PDF):**
- Executive summary with key takeaways
- Detailed opportunity assessments for each NAICS-matched opportunity
  - Disposition (ACTIONABLE / MONITOR / IGNORE)
  - Key dates and timelines
  - Acquisition summary
  - Contract details
  - Relevance to business capabilities
  - Recommended actions
- Clickable links to SAM.gov and additional resources
- Professional formatting optimized for email distribution

---

## Documentation

- **HOW_TO_RUN.md** - Detailed step-by-step guide for running scripts
- **sam_pull.py** - Full documentation in script docstring

---

## Configuration

Required environment variables in `.env`:

```bash
# SAM.gov API Key (required)
SAM_API_KEY=your-api-key-here

# Organization ID from seed command (required)
DEFAULT_ORG_ID=your-org-uuid

# LLM Configuration (required for AI summaries)
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1
# Or use alternative LLM providers (Ollama, LiteLLM, etc.)

# Object storage (required)
USE_OBJECT_STORAGE=true
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=admin
MINIO_SECRET_KEY=changeme
MINIO_BUCKET_UPLOADS=curatore-uploads

# Database (required)
DATABASE_URL=sqlite+aiosqlite:///./data/curatore.db

# Celery/Redis (required for background jobs)
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
```

**PDF Generation (optional):**

To enable PDF report generation, install system dependencies:

```bash
# macOS
brew install pango cairo gdk-pixbuf libffi

# Then reinstall weasyprint
pip install --force-reinstall weasyprint
```

Without these dependencies, the script will generate Markdown reports only (PDF generation will be skipped with a warning).

---

## Troubleshooting

### "command not found: python"

**Solution:** Use Docker method (no Python needed):
```bash
docker-compose exec backend python /app/scripts/sam/sam_pull.py
```

Or use `python3` explicitly:
```bash
python3 scripts/sam/sam_pull.py
```

### "SAM_API_KEY not found"

**Cause:** Missing environment variable

**Solution:** Add to `.env` file:
```bash
echo "SAM_API_KEY=your-api-key-here" >> .env
```

Get API key from: https://sam.gov/ → Data Services → API Access

### "DEFAULT_ORG_ID not found"

**Cause:** Database not seeded

**Solution:**
```bash
cd backend
source venv/bin/activate
python -m app.commands.seed --create-admin
# Copy the organization ID to .env
cd ..
echo "DEFAULT_ORG_ID=your-org-uuid" >> .env
```

### "Connection refused" / "Object storage is not enabled"

**Cause:** Services not running or storage not initialized

**Solution:**
```bash
./scripts/dev-up.sh
# Wait 30 seconds for services to start
./scripts/init_storage.sh
```

### "Bucket not found"

**Cause:** MinIO buckets not initialized

**Solution:**
```bash
./scripts/init_storage.sh
```

### "No module named 'app'"

**Cause:** Virtual environment not activated (if not using Docker)

**Solution:** Activate backend venv:
```bash
cd backend
source venv/bin/activate
cd ..
python scripts/sam/sam_pull.py
```

---

## Advanced Usage

### Custom Date Range

The script defaults to pulling opportunities from the last 7 days. To change this:

```python
# Edit scripts/sam/sam_pull.py (around line 297)
# Change these lines:
POSTED_FROM = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%m/%d/%Y")
POSTED_TO = datetime.now(timezone.utc).strftime("%m/%d/%Y")

# Examples:
# Last 24 hours: timedelta(days=1)
# Last 30 days: timedelta(days=30)
# Specific date: "01/15/2026"
```

**Note:** When running manually with a different date range, the output files still use today's date in the filename. This ensures one file per day regardless of the query period.

### Additional Agencies

Add more agencies to filter:

```python
# Edit scripts/sam/sam_pull.py
DHS_AGENCIES = [
    "U.S. Immigration and Customs Enforcement",
    "U.S. Customs and Border Protection",
    "U.S. Citizenship and Immigration Services",
    "Federal Emergency Management Agency",  # Add more
    "Transportation Security Administration",
]
```

### Additional Notice Types

Filter for more notice types:

```python
# Edit scripts/sam/sam_pull.py (around line 272)
NOTICE_TYPES = [
    "Sources Sought",
    "Special Notice",
    "Solicitation",
    "Combined Synopsis/Solicitation",
    "Presolicitation",  # Add more
    "Intent to Bundle Requirements",
]
```

### Custom NAICS Codes

The script filters opportunities by NAICS codes to identify relevant contracts. To customize:

```python
# Edit scripts/sam/sam_pull.py (around line 279)
TARGET_NAICS_CODES = {
    "541511",  # Custom Computer Programming Services
    "541512",  # Computer Systems Design Services
    "541519",  # Other Computer Related Services
    "518210",  # Data Processing, Hosting, and Related Services
    "541513",  # Computer Facilities Management Services
    "541611",  # Administrative Management Consulting
    "541618",  # Other Management Consulting Services
    "541690",  # Other Scientific and Technical Consulting Services
    "541330",  # Engineering Services
    # Add your custom NAICS codes here
}
```

**Benefits of NAICS Filtering:**
- Only downloads attachments for matched opportunities (saves bandwidth)
- Only fetches descriptions for matched opportunities (saves API calls)
- AI analysis focuses only on relevant opportunities
- Cleaner, more actionable intelligence reports

---

## Monitoring

### View Logs

```bash
# View real-time script output
tail -f logs/sam_pull.log

# View last 50 lines
tail -50 logs/sam_pull.log

# Search for errors
grep -i error logs/sam_pull.log
```

### Check Artifact Records

```bash
# Via backend container
docker-compose exec backend python -c "
from app.services.database_service import database_service
from app.database.models import Artifact
from sqlalchemy import select, desc
import asyncio

async def check():
    async with database_service.get_session() as session:
        result = await session.execute(
            select(Artifact)
            .where(Artifact.document_id.like('sam_%'))
            .order_by(desc(Artifact.created_at))
            .limit(10)
        )
        artifacts = result.scalars().all()
        print(f'Found {len(artifacts)} SAM.gov artifacts')
        for a in artifacts:
            print(f'  - {a.original_filename} ({a.file_size} bytes) at {a.created_at}')

asyncio.run(check())
"
```

### Check MinIO Objects

```bash
# List SAM.gov files in MinIO
docker-compose exec backend python -c "
from app.services.minio_service import get_minio_service

minio = get_minio_service()
objects = minio.list_objects(
    bucket='curatore-uploads',
    prefix='${DEFAULT_ORG_ID}/sam/',
    recursive=True
)

print(f'Found {len(objects)} files in sam/ folder')
for obj in objects:
    print(f'  - {obj[\"key\"]} ({obj[\"size\"]} bytes)')
"
```

**Expected Folder Structure:**
```
{org_id}/sam/
├── daily_extract/
│   └── sam_pull_YYYYMMDD.json
├── daily_extract_summary/
│   ├── sam_pull_summary_YYYYMMDD.md
│   └── sam_pull_summary_YYYYMMDD.pdf
└── {solicitationNumber}/
    └── [attachments]
```

---

## API Reference

### SAM.gov Opportunities API v2

**Endpoint:** `https://api.sam.gov/opportunities/v2/search`

**Authentication:** API key via `X-API-KEY` header or `api_key` query parameter

**Documentation:** https://open.gsa.gov/api/opportunities-api/

**Rate Limits:**
- 1000 requests per hour per API key
- 10 requests per second

**Key Parameters:**
- `postedFrom` - Start date (MM/DD/YYYY)
- `postedTo` - End date (MM/DD/YYYY)
- `noticeType` - Notice type filter (comma-separated)
- `departmentName` - Department filter
- `limit` - Results per page (max 100)
- `offset` - Pagination offset

---

## Features

### Implemented
- ✅ NAICS code filtering for targeted opportunity identification
- ✅ Automatic resource file downloads (PDFs, DOCs, etc.)
- ✅ Full description fetching from SAM.gov API
- ✅ AI-powered opportunity analysis and classification
- ✅ Executive intelligence summaries
- ✅ Markdown and PDF report generation with clickable links
- ✅ Duplicate detection (skip already-pulled opportunities in backlog)
- ✅ Retry logic with exponential backoff for API reliability
- ✅ Organized folder structure (daily_extract, daily_extract_summary, attachments)
- ✅ Database tracking for all files (frontend visibility)
- ✅ Error tracking (descriptions not found, download failures)
- ✅ Idempotent operations (safe to run multiple times per day)

### Future Enhancements
- [ ] Add `--dry-run` flag for testing without uploads
- [ ] Add `--date-range` CLI argument for custom date ranges
- [ ] Add `--agencies` CLI argument for custom agency filters
- [ ] Email notifications on new NAICS-matched opportunities
- [ ] Slack/Teams webhook integration for real-time alerts
- [ ] Opportunity change tracking (detect amendments/updates)
- [ ] Trend analysis (identify recurring keywords, agencies, contract types)
- [ ] Integration with bid/no-bid decision workflow

---

## Related Documentation

- **Main Scripts README:** `../README.md`
- **Curatore Documentation:** `../../CLAUDE.md`
- **Storage Configuration:** `../../docs/CONFIGURATION.md`
- **API Documentation:** `../../docs/API_DOCUMENTATION.md`

---

**For detailed execution instructions, see:** `HOW_TO_RUN.md`
