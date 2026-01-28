#!/usr/bin/env python3
"""
SAM.gov DHS Opportunities Daily Pull Script

Fetches opportunities from SAM.gov API for DHS components (ICE, CBP, USCIS)
and stores them in object storage with date-based folder organization.

UPLOAD METHODS:
    - All files uploaded directly to MinIO with custom folder structure
    - Date-based organization for daily extracts and summaries
    - Solicitation-based organization for resource files

FILES UPLOADED:
    Consolidated JSON file (all opportunities with full descriptions):
      Uploaded directly to MinIO
      Path: {org_id}/sam/pull_{YYYYMMDD}/sam_pull_{YYYYMMDD}.json
      Filename: sam_pull_{date}.json
      Contains all opportunities with NAICS-matched ones having full descriptions

    Daily Summary Report (AI-powered analysis - Markdown + PDF):
      Uploaded directly to MinIO
      Path: {org_id}/sam/pull_{YYYYMMDD}/sam_pull_summary_{YYYYMMDD}.md
      Path: {org_id}/sam/pull_{YYYYMMDD}/sam_pull_summary_{YYYYMMDD}.pdf
      Filenames: sam_pull_summary_{date}.md, sam_pull_summary_{date}.pdf

    Resource files (PDFs, DOCs, etc. from resourceLinks):
      Uploaded directly to MinIO with custom folder structure
      Path: {org_id}/sam/{solicitation_number}/{filename}
      Original filenames preserved from SAM.gov
      Files with same name are overwritten
      Only downloads for NAICS-matched opportunities

FOLDER STRUCTURE:
    {org_id}/sam/
      pull_{YYYYMMDD}/                      # Date-based folders for daily runs
        sam_pull_{YYYYMMDD}.json            # Consolidated JSON
        sam_pull_summary_{YYYYMMDD}.md      # Daily summary (Markdown)
        sam_pull_summary_{YYYYMMDD}.pdf     # Daily summary (PDF)
      {solicitationNumber}/                 # Solicitation-based folders
        {filename}                          # Resource files

SETUP INSTRUCTIONS:
    1. Ensure Curatore v2 services are running:
       $ ./scripts/dev-up.sh

    2. Initialize storage (if not already done):
       $ ./scripts/init_storage.sh

    3. Initialize database and get organization ID (if not already done):
       $ cd backend
       $ python -m app.commands.seed --create-admin
       # Copy the organization ID from output

    4. Configure environment variables in .env file:
       SAM_API_KEY=your-sam-gov-api-key-here
       DEFAULT_ORG_ID=your-org-uuid-from-seed-command
       API_URL=http://localhost:8000  # Backend API URL
       API_KEY=your-api-key  # Optional, only if ENABLE_AUTH=true

    5. Get SAM.gov API Key:
       - Register at https://sam.gov/
       - Navigate to Data Services > API Access
       - Generate API key

PYTHON VIRTUAL ENVIRONMENT SETUP:
    This script requires Python 3.12+ and backend dependencies.

    Option 1: Use existing backend virtual environment (RECOMMENDED):
    $ cd backend
    $ source venv/bin/activate  # On macOS/Linux
    $ venv\\Scripts\\activate     # On Windows
    $ cd ..
    $ python scripts/sam/sam_pull.py

    Option 2: Create dedicated virtual environment for scripts:
    $ python3 -m venv venv
    $ source venv/bin/activate  # On macOS/Linux
    $ venv\\Scripts\\activate     # On Windows
    $ pip install -r backend/requirements.txt
    $ python scripts/sam/sam_pull.py

    Option 3: Use Docker (no local Python needed):
    $ docker-compose exec backend python /app/scripts/sam_pull.py

RUN THE SCRIPT:
    After activating virtual environment:
    $ python scripts/sam_pull.py

    Or use python3 explicitly:
    $ python3 scripts/sam_pull.py

    Or via Docker:
    $ docker-compose exec backend python /app/scripts/sam_pull.py

SCHEDULE WITH CRON:
    Daily at 6 AM using virtual environment:
    $ crontab -e
    0 6 * * * cd /path/to/curatore-v2 && source backend/venv/bin/activate && python scripts/sam_pull.py >> logs/sam_pull.log 2>&1

    Or using Docker (no venv needed):
    $ crontab -e
    0 6 * * * cd /path/to/curatore-v2 && docker-compose exec -T backend python /app/scripts/sam_pull.py >> logs/sam_pull.log 2>&1

VIEW RESULTS:
    - Frontend: http://localhost:3000/storage
      Navigate to: Default Storage > {org_id} > sam/
        - pull_{YYYYMMDD}/ (Daily extracts and summaries organized by date)
          - sam_pull_{YYYYMMDD}.json
          - sam_pull_summary_{YYYYMMDD}.md
          - sam_pull_summary_{YYYYMMDD}.pdf
        - {solicitationNumber}/ (Resource files organized by solicitation)
    - MinIO Console: http://localhost:9001
      Login: minioadmin/minioadmin
      Browse: curatore-uploads/{org_id}/sam/

WHAT IT DOES:
    1. Fetches opportunities posted in last 24 hours from SAM.gov
    2. Filters for DHS agencies (ICE, CBP, USCIS)
    3. Filters for notice types: Sources Sought, Special Notice, Solicitation
    4. Identifies opportunities matching target NAICS codes
    5. For NAICS-matched opportunities only:
       - Fetches full description from description API (adds api_key parameter)
       - Merges description into opportunity record
       - Downloads files from resourceLinks URLs (adds api_key parameter)
       - Uploads files to {org_id}/sam/{solicitationNumber}/ folders
    6. Uploads consolidated JSON file to {org_id}/sam/pull_{YYYYMMDD}/ folder (all opportunities)
    7. Generates AI-powered daily summary report:
       - Analyzes each NAICS-matched opportunity using LLM
       - Classifies opportunity type (RFI, Industry Day, RFP, etc.)
       - Summarizes key information, timelines, and evaluation
       - Creates markdown report with all analyses
       - Converts markdown to PDF for email-friendly distribution
       - Uploads to {org_id}/sam/pull_{YYYYMMDD}/ (both .md and .pdf)
    8. Displays summary with storage locations organized by date

IDEMPOTENCY:
    This script is safe to run multiple times per day:
    - Consolidated JSON file is overwritten (same filename per day)
    - Daily summary report is regenerated with latest data (overwrites existing)
    - Resource files are created/updated by filename
    - All files organized by date in {org_id}/sam/pull_{YYYYMMDD}/ folders

LLM CONFIGURATION:
    The daily summary uses the LLM configured in config.yml or environment variables.
    If LLM is unavailable, the script continues without generating the summary.
    Required settings: OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL

OUTPUT FORMATS:

    Consolidated JSON (sam_pull_YYYYMMDD.json):
    {
      "metadata": {
        "pulled_at_utc": "2026-01-26T12:00:00.000000",
        "source": "SAM.gov Opportunities API",
        "record_count": 10,
        "naics_matched_count": 2
      },
      "opportunities": [
        {
          "noticeId": "1234567890",
          "solicitationNumber": "70ABC123456",
          "title": "Software Development Services",
          ... (basic SAM.gov fields) ...,
          "_naics_match": true,
          "_full_description": {
            ... (complete description from description API) ...
          },
          "resourceLinks": [
            {"url": "...", "name": "RFI Document"}
          ]
        },
        {
          "noticeId": "9876543210",
          "title": "Another Opportunity",
          ... (basic SAM.gov fields) ...,
          "_naics_match": false,
          "_errors": [
            {
              "field": "description",
              "message": "Description Not Found"
            }
          ]
        }
      ]
    }

    Note:
    - Only NAICS-matched opportunities will have _full_description field
    - If description API returns an error (e.g., "Description Not Found"),
      the opportunity will include an _errors list with the error details
    - Non-NAICS-matched opportunities will not have _full_description

    Resource files: Downloaded from resourceLinks and stored by solicitation number

TROUBLESHOOTING:
    - "SAM_API_KEY not found": Add SAM_API_KEY to .env file
    - "DEFAULT_ORG_ID not found": Run seed command and set in .env
    - "Object storage is not enabled": Set USE_OBJECT_STORAGE=true in .env
    - "Connection refused": Ensure services are running (./scripts/dev-up.sh)
    - "Bucket not found": Run ./scripts/init_storage.sh
"""

import os
import sys
import json
import asyncio
import httpx
import re
import mimetypes
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from uuid import UUID
from dotenv import load_dotenv

# Optional PDF generation support
try:
    import markdown
    from weasyprint import HTML, CSS
    PDF_AVAILABLE = True
except (ImportError, OSError) as e:
    PDF_AVAILABLE = False
    PDF_ERROR = str(e)

# Load environment variables first
load_dotenv()

# Use SAM_MINIO_ENDPOINT if available (for local script execution)
# Otherwise fall back to MINIO_ENDPOINT
sam_minio_endpoint = os.getenv("SAM_MINIO_ENDPOINT")
if sam_minio_endpoint:
    os.environ["MINIO_ENDPOINT"] = sam_minio_endpoint
    # Temporarily disable config.yml to force environment variable usage
    os.environ["CONFIG_PATH"] = "/dev/null"  # Point to non-existent file
    print(f"ℹ️  Using SAM script MinIO endpoint: {sam_minio_endpoint}")

# Ensure DATABASE_URL points to the backend database (not project root)
# This script runs from project root, but database is in backend/data/
database_url = os.getenv("DATABASE_URL", "")
if "./data/" in database_url:
    # Convert relative path to absolute path pointing to backend/data/
    project_root_str = str(Path(__file__).parent.parent.parent)
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{project_root_str}/backend/data/curatore.db"
    print(f"ℹ️  Using backend database: backend/data/curatore.db")

# Add backend to Python path to import configuration
# Script is in scripts/sam/, so we need to go up 2 levels to get to project root
project_root = Path(__file__).parent.parent.parent
backend_path = project_root / "backend"
sys.path.insert(0, str(backend_path))

# NOW import app modules (after environment is configured)
from app.config import settings
from app.services.llm_service import LLMService

# Import backend upload helper for proper UUID document IDs
sam_scripts_path = project_root / "scripts" / "sam"
sys.path.insert(0, str(sam_scripts_path))
from backend_upload import upload_file_to_backend

# Validate required environment variables
SAM_API_KEY = os.getenv("SAM_API_KEY")
if not SAM_API_KEY:
    raise RuntimeError(
        "SAM_API_KEY not found in environment.\n"
        "Get your API key from https://sam.gov/ > Data Services > API Access\n"
        "Then add to .env file: SAM_API_KEY=your-api-key-here"
    )

DEFAULT_ORG_ID = settings.default_org_id
if not DEFAULT_ORG_ID:
    raise RuntimeError(
        "DEFAULT_ORG_ID not found in environment.\n"
        "Run: cd backend && python -m app.commands.seed --create-admin\n"
        "Then add the organization ID to .env file: DEFAULT_ORG_ID=your-org-uuid"
    )

BASE_URL = "https://api.sam.gov/opportunities/v2/search"

# DHS sub-agencies of interest
DHS_AGENCIES = [
    "U.S. Immigration and Customs Enforcement",
    "U.S. Customs and Border Protection",
    "U.S. Citizenship and Immigration Services",
]

# Notice types of interest (SAM uses noticeType)
NOTICE_TYPES = [
    "Sources Sought",
    "Special Notice",          # commonly used for Industry Days
    "Solicitation",
    "Combined Synopsis/Solicitation",
]

# NAICS codes we care about
TARGET_NAICS_CODES = {
    "541511",
    "541512",
    "541519",
    "518210",
    "541513",
    "541611",
    "541618",
    "541690",
    "541330",
}

POSTED_FROM = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%m/%d/%Y")
POSTED_TO = datetime.now(timezone.utc).strftime("%m/%d/%Y")

HEADERS = {
    "X-API-KEY": SAM_API_KEY
}


def fetch_opportunities():
    """
    Fetch all DHS opportunities posted yesterday using totalRecords-driven pagination.
    Returns consolidated list of opportunity records.

    Uses retry logic with exponential backoff for resilience against API timeouts.
    """
    import time

    results = []
    limit = 100
    offset = 0
    max_retries = 3
    timeout = 90  # Increased timeout for SAM.gov API

    base_params = {
        "api_key": SAM_API_KEY,
        "postedFrom": POSTED_FROM,
        "postedTo": POSTED_TO,
        "organizationName": "HOMELAND SECURITY, DEPARTMENT OF",
        "limit": limit,
    }

    def make_request_with_retry(params, attempt=1):
        """Make HTTP request with exponential backoff retry logic."""
        try:
            response = httpx.get(BASE_URL, headers=HEADERS, params=params, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            if attempt < max_retries:
                wait_time = 2 ** attempt  # Exponential backoff: 2, 4, 8 seconds
                print(f"  ⚠ Request timed out (attempt {attempt}/{max_retries}), retrying in {wait_time}s...")
                time.sleep(wait_time)
                return make_request_with_retry(params, attempt + 1)
            else:
                raise RuntimeError(
                    f"SAM.gov API failed after {max_retries} attempts. "
                    f"The API may be slow or unavailable. Try again later."
                ) from e
        except httpx.HTTPStatusError as e:
            if e.response.status_code >= 500 and attempt < max_retries:
                wait_time = 2 ** attempt
                print(f"  ⚠ Server error (attempt {attempt}/{max_retries}), retrying in {wait_time}s...")
                time.sleep(wait_time)
                return make_request_with_retry(params, attempt + 1)
            else:
                raise

    # First call to determine totalRecords
    print(f"  Fetching initial batch (timeout: {timeout}s)...")
    data = make_request_with_retry(base_params)

    total_records = data.get("totalRecords", 0)
    opportunities = data.get("opportunitiesData", [])
    results.extend(opportunities)
    print(f"  Found {total_records} total records, retrieved {len(opportunities)} in first batch")

    # Calculate remaining calls
    batch_num = 1
    while offset + limit < total_records:
        offset += limit
        batch_num += 1
        params = dict(base_params)
        params["offset"] = offset

        print(f"  Fetching batch {batch_num} (offset {offset})...")

        try:
            data = make_request_with_retry(params)

            batch = data.get("opportunitiesData", [])
            if not batch:
                break

            results.extend(batch)
            print(f"  Retrieved {len(batch)} records (total so far: {len(results)})")

        except httpx.HTTPStatusError as e:
            # SAM.gov API sometimes fails on pagination - continue with partial results
            print(f"  ⚠ Failed to fetch batch {batch_num}: {e.response.status_code} error")
            print(f"  ℹ️  Continuing with {len(results)} records retrieved so far")
            break
        except Exception as e:
            # Other errors - log and continue with partial results
            print(f"  ⚠ Failed to fetch batch {batch_num}: {str(e)}")
            print(f"  ℹ️  Continuing with {len(results)} records retrieved so far")
            break

    if len(results) < total_records:
        print(f"  ⚠ Retrieved {len(results)}/{total_records} records (SAM.gov API pagination issue)")

    return results


def fetch_opportunity_description(description_url):
    """
    Fetch the full description content for an opportunity from its description URL.

    Args:
        description_url: URL to the opportunity description API endpoint

    Returns:
        Tuple of (description_data, error_message)
        - (dict, None) if successful
        - (None, error_string) if failed
    """
    import time

    max_retries = 2
    timeout = 60  # Increased timeout

    # Add api_key to URL parameters (use & if URL already has query params)
    separator = "&" if "?" in description_url else "?"
    url_with_key = f"{description_url}{separator}api_key={SAM_API_KEY}"

    for attempt in range(1, max_retries + 1):
        try:
            response = httpx.get(url_with_key, headers=HEADERS, timeout=timeout)
            response.raise_for_status()
            data = response.json()

            # Check if response contains an error message
            if isinstance(data, dict) and "errorMessage" in data:
                return None, data["errorMessage"]

            return data, None

        except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            if attempt < max_retries:
                wait_time = 2 ** attempt
                time.sleep(wait_time)
                continue
            return None, f"Timeout after {max_retries} attempts"

        except httpx.HTTPStatusError as e:
            return None, f"HTTP {e.response.status_code}: {e.response.text}"

        except Exception as e:
            return None, str(e)

    return None, "Unknown error"


async def download_resource_links(opportunities, pulled_at):
    """
    Download files from resourceLinks for NAICS-matched opportunities.

    Files are uploaded directly to MinIO (not via backend API) to maintain
    custom folder structure organized by solicitationNumber:
        {org_id}/sam/{solicitationNumber}/filename.pdf

    This preserves the legacy SAM file organization that users expect.
    Files with the same name will be overwritten.

    Args:
        opportunities: List of opportunity records
        pulled_at: Timestamp of the pull

    Returns:
        Dict mapping notice_id to list of uploaded filenames
    """
    from minio import Minio
    from io import BytesIO

    # Initialize MinIO client for direct upload
    minio_client = Minio(
        "localhost:9000",
        access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        secure=False
    )
    bucket = os.getenv("MINIO_BUCKET_UPLOADS", "curatore-uploads")

    # Ensure bucket exists
    if not minio_client.bucket_exists(bucket):
        minio_client.make_bucket(bucket)

    results = {}

    print(f"\nDownloading resource files for NAICS-matched opportunities...")

    for opp in opportunities:
        if not opp.get("_naics_match"):
            continue

        notice_id = opp.get("noticeId")
        solicitation_number = opp.get("solicitationNumber", notice_id)
        resource_links = opp.get("resourceLinks", [])

        if not resource_links:
            continue

        print(f"\n  Processing {solicitation_number} ({notice_id}):")
        artifact_ids = []

        for link in resource_links:
            # resourceLinks can be strings or dicts
            if isinstance(link, dict):
                url = link.get("url")
                link_name = link.get("name", "unknown")
            else:
                url = link
                link_name = "unknown"

            if not url:
                continue

            try:
                # Add api_key to URL parameters (use & if URL already has query params)
                separator = "&" if "?" in url else "?"
                url_with_key = f"{url}{separator}api_key={SAM_API_KEY}"

                print(f"    Downloading {link_name}...")

                # Retry logic for resource downloads
                max_retries = 2
                for attempt in range(1, max_retries + 1):
                    try:
                        response = httpx.get(url_with_key, headers=HEADERS, timeout=90, follow_redirects=True)
                        response.raise_for_status()
                        break
                    except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
                        if attempt < max_retries:
                            import time
                            wait_time = 2 ** attempt
                            print(f"      Timeout, retrying in {wait_time}s...")
                            time.sleep(wait_time)
                        else:
                            raise

                # Get filename from Content-Disposition header or URL
                filename = None
                if "Content-Disposition" in response.headers:
                    matches = re.findall(r'filename="?([^"]+)"?', response.headers["Content-Disposition"])
                    if matches:
                        filename = matches[0]

                if not filename:
                    # Extract from URL
                    filename = url.split("/")[-1].split("?")[0]
                    if not filename or filename == "":
                        filename = f"{link_name}.dat"

                # Get content type
                content_type = response.headers.get("content-type", "application/octet-stream")
                if content_type == "application/octet-stream" and filename:
                    # Try to guess from filename
                    guessed_type, _ = mimetypes.guess_type(filename)
                    if guessed_type:
                        content_type = guessed_type

                # Upload directly to MinIO with custom folder structure
                file_bytes = response.content
                file_size = len(file_bytes)
                file_stream = BytesIO(file_bytes)

                # Build path: {org_id}/sam/{solicitation_number}/{filename}
                object_key = f"{DEFAULT_ORG_ID}/sam/{solicitation_number}/{filename}"

                try:
                    # Upload to MinIO (overwrites if file already exists)
                    result = minio_client.put_object(
                        bucket_name=bucket,
                        object_name=object_key,
                        data=file_stream,
                        length=file_size,
                        content_type=content_type,
                        metadata={
                            "source": "sam.gov",
                            "notice_id": notice_id,
                            "solicitation_number": solicitation_number,
                            "link_name": link_name,
                            "pulled_at": pulled_at.isoformat(),
                        }
                    )

                    # Track filename (not UUID since we're using custom paths)
                    artifact_ids.append(filename)
                    print(f"    ✓ Uploaded {filename} ({file_size:,} bytes)")
                    print(f"      Path: {bucket}/{object_key}")

                except Exception as upload_error:
                    print(f"    ✗ Failed to upload {filename}: {upload_error}")
                    continue

            except Exception as e:
                print(f"    ✗ Failed to download {link_name}: {e}")

        results[notice_id] = artifact_ids

    return results



# --- BEGIN: Helper to extract key acquisition dates ---
def extract_key_dates(opp):
    """
    Extract key acquisition-related dates from SAM fields and free text.
    Returns a dict of normalized date signals.
    """
    dates = {}

    # Direct SAM fields
    if opp.get("postedDate"):
        dates["posted_date"] = opp.get("postedDate")
    if opp.get("responseDeadLine"):
        dates["response_deadline"] = opp.get("responseDeadLine")

    # Attempt to infer award date
    if opp.get("type", "").lower() == "award notice":
        dates["award_date"] = opp.get("postedDate")

    # Scan description text for common date signals
    desc = ""
    if isinstance(opp.get("_full_description"), dict):
        desc = opp["_full_description"].get("description", "")

    patterns = {
        "rfp_release_date": r"(RFP|solicitation).*?(released|issue[d]?)\s+on\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        "rfp_due_date": r"(RFP|proposal).*?(due|deadline).*?([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        "industry_day": r"(industry day).*?([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        "updated_date": r"(updated|amended|revision).*?([A-Za-z]+\s+\d{1,2},\s+\d{4})",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, desc, re.IGNORECASE)
        if match:
            dates[key] = match.group(match.lastindex)

    return dates
# --- END: Helper to extract key acquisition dates ---


def resolve_agency_component(opp):
    """
    Normalize agency / component naming using authoritative SAM fields.
    Returns (agency, component).
    """

    full_path = opp.get("fullParentPathName")

    if full_path:
        # Example:
        # "HOMELAND SECURITY, DEPARTMENT OF.OFFICE OF PROCUREMENT OPERATIONS"
        parts = [p.strip() for p in full_path.split(".") if p.strip()]

        if len(parts) >= 2:
            agency = parts[0].title()
            component = parts[1].title()
            return agency, component

        if len(parts) == 1:
            return parts[0].title(), "Unknown"

    # Fallbacks (less reliable)
    agency = (
        opp.get("departmentName")
        or opp.get("agency")
        or "Unknown"
    )

    component = (
        opp.get("subTier")
        or opp.get("subAgency")
        or opp.get("officeName")
        or "Unknown"
    )

    return agency, component


async def analyze_opportunity_with_llm(opp, llm_service):
    """
    Use LLM to analyze a single opportunity and generate a summary.

    Args:
        opp: Opportunity record with description and metadata
        llm_service: Initialized LLMService instance

    Returns:
        Markdown string with analysis or None if LLM unavailable
    """
    if not llm_service.is_available:
        return None

    notice_id = opp.get("noticeId", "Unknown")
    title = opp.get("title", "Untitled")
    solicitation_number = opp.get("solicitationNumber", "N/A")
    notice_type = opp.get("type", "Unknown")
    posted_date = opp.get("postedDate", "Unknown")
    response_deadline = opp.get("responseDeadLine", "Not specified")

    # Build context for LLM
    context = f"""Opportunity: {title}
Notice ID: {notice_id}
Solicitation Number: {solicitation_number}
Type: {notice_type}
Posted Date: {posted_date}
Response Deadline: {response_deadline}

"""
    agency, component = resolve_agency_component(opp)
    context += f"Agency: {agency}\nComponent: {component}\n"
    context += f"Notice Type (SAM): {notice_type}\n\n"

    # Add full description if available
    if "_full_description" in opp:
        description = opp["_full_description"]
        # Extract relevant fields from description
        if isinstance(description, dict):
            if "description" in description:
                context += f"Description:\n{description['description']}\n\n"
            if "additionalInfoLink" in description:
                context += f"Additional Info: {description['additionalInfoLink']}\n\n"

    # Add resource links info
    resource_links = opp.get("resourceLinks", [])
    if resource_links:
        context += f"Attached Files: {len(resource_links)} file(s) available\n\n"

    # Add extracted key dates to context
    key_dates = extract_key_dates(opp)
    if key_dates:
        context += "Key Dates Identified:\n"
        for k, v in key_dates.items():
            context += f"- {k.replace('_', ' ').title()}: {v}\n"
        context += "\n"

    try:
        system_prompt = """
You are an internal business development and acquisition analyst for Amivero, LLC.

ABOUT AMIVERO:
- 8(a), Woman-Owned Small Business (WOSB)
- Primary customer: U.S. Department of Homeland Security (DHS)
  - Current customers: CBP, USCIS, ICE
  - Strategic growth targets: TSA, CISA, FEMA
- Core capabilities:
  - Artificial Intelligence & Advanced Analytics
  - Fraud Detection & Financial Crimes
  - SecDevOps & Cloud Engineering
  - Software Development & Systems Integration
  - RPA & Intelligent Automation
  - Program & Project Management
  - Business Intelligence & Data Platforms

PRIMARY GOAL:
Provide a concise, executive-ready assessment of whether this SAM.gov notice represents a real, actionable opportunity for Amivero.

GENERAL GUIDANCE:
- Most Special Notices, Award Notices, and Sole Source Justifications are NOT actionable.
- Be decisive and concise.
- Avoid FAR explanations unless they materially affect actionability.
- Optimize for executive consumption and downstream use in email or PDF.

OUTPUT REQUIREMENTS:
- Use the exact structure below.
- Keep language professional and neutral.
- Use short paragraphs and bullet points.
- Ensure formatting is suitable for rich-text email and PDF rendering.

REQUIRED OUTPUT FORMAT:

### Opportunity Overview
**Disposition**: ACTIONABLE | MONITOR | IGNORE  
**Agency / Component**: <Agency, Subcomponent>  
**Notice Type**: <SAM notice type>  
**NAICS**: <comma-separated list>

### Key Dates (if applicable)
- Clearly list and label any of the following when present:
  - Award date
  - RFP release date
  - Updated or amended due date (highlight as UPDATE)
  - Proposal due date
  - Industry Day date

### Acquisition Summary
- 2–4 concise bullets describing what the government is buying and why

### Contract / Procurement Details
- Contract type
- Estimated value
- Period of performance
- Incumbent or awardee (if applicable)

### Relevance to Amivero
- Explicitly connect to Amivero DHS strategy and capabilities
- Or state “Not relevant to Amivero”

### Recommended Action
- One clear sentence
"""

        client = llm_service._client
        if not client:
            return None

        resp = client.chat.completions.create(
            model=settings.openai_model,
            temperature=0.3,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": context},
            ],
        )

        return resp.choices[0].message.content

    except Exception as e:
        print(f"    ⚠ LLM analysis failed for {notice_id}: {e}")
        return None


# --- BEGIN: Executive Intelligence Summary LLM step ---
# Helper to classify “headline” opportunity types (for executive summary headline list)
def classify_headline_opportunity(analysis_text):
    """
    Determine whether an analyzed opportunity should appear
    in the executive headline list.
    """
    text = analysis_text.lower()

    if "sources sought" in text or "rfi" in text:
        return "RFI / Sources Sought"
    if "industry day" in text:
        return "Industry Day"
    if "solicitation" in text or "rfp" in text:
        return "Solicitation / RFP"

    return None


async def generate_executive_summary(analyzed_entries, headline_items, llm_service):
    if not llm_service.is_available:
        return None

    summary_context = "HEADLINE OPPORTUNITIES:\n\n"

    if headline_items:
        for item in headline_items:
            summary_context += (
                f"- [{item['category']}] {item['title']}\n"
                f"  Agency: {item['agency']} / {item['component']}\n"
                f"  Link: {item['link']}\n\n"
            )
    else:
        summary_context += "None identified.\n\n"

    summary_context += "DETAILED ANALYSIS INPUT:\n\n"
    for entry in analyzed_entries:
        summary_context += f"- {entry}\n\n"

    system_prompt = """
You are a senior Business Development executive at Amivero, LLC.

Your task is to produce an executive-ready daily SAM.gov intelligence summary.

REQUIRED STRUCTURE:

## New & Updated Government Actions
- List ONLY the following when present:
  - New RFIs / Sources Sought
  - Industry Day announcements
  - Newly released solicitations (RFPs)
  - Updates or amendments to previously released RFIs or RFPs (clearly label as UPDATE)
- Each bullet MUST include:
  - Title
  - Agency / Component
  - Direct SAM.gov link

If none exist, explicitly state: “No new RFIs, Industry Days, or Solicitations released in this period.”

## Executive Takeaways for Amivero
- 3–6 concise bullets focused on:
  - DHS component activity (CBP, USCIS, ICE, TSA, CISA, FEMA)
  - Signals relevant to Amivero’s AI, fraud, SecDevOps, automation, and digital services focus
  - What is worth monitoring vs. safely ignoring

STYLE RULES:
- Bullet-driven
- No long prose
- No FAR explanations
- No restating full opportunity descriptions
- Optimized for email and PDF
"""

    client = llm_service._client
    resp = client.chat.completions.create(
        model=settings.openai_model,
        temperature=0.3,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": summary_context},
        ],
    )

    return resp.choices[0].message.content
# --- END: Executive Intelligence Summary LLM step ---


def markdown_to_pdf(markdown_content, output_stream=None):
    """
    Convert markdown content to PDF.

    Args:
        markdown_content: Markdown string to convert
        output_stream: Optional BytesIO stream to write PDF to (if None, returns bytes)

    Returns:
        BytesIO stream with PDF content, or None if PDF generation is unavailable

    Raises:
        RuntimeError: If PDF libraries are not available
    """
    if not PDF_AVAILABLE:
        raise RuntimeError(
            f"PDF generation is not available. Install system dependencies:\n"
            f"  macOS: brew install pango cairo gdk-pixbuf libffi\n"
            f"  Then reinstall: pip install weasyprint\n"
            f"Error: {PDF_ERROR}"
        )

    # Convert markdown to HTML with link auto-detection
    html_content = markdown.markdown(
        markdown_content,
        extensions=[
            'markdown.extensions.tables',
            'markdown.extensions.fenced_code',
            'markdown.extensions.nl2br',
            'markdown.extensions.sane_lists',
        ]
    )

    # Auto-linkify plain URLs in the HTML (for any URLs not already in markdown format)
    import re
    url_pattern = r'(?<!href=")(?<!href=\')(?<!")(https?://[^\s<>"]+)(?![^<]*</a>)'
    html_content = re.sub(url_pattern, r'<a href="\1">\1</a>', html_content)

    # Add CSS styling for better PDF appearance
    css = CSS(string="""
        @page {
            size: Letter;
            margin: 1in;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
            font-size: 11pt;
            line-height: 1.6;
            color: #333;
        }
        h1 {
            color: #1a1a1a;
            font-size: 24pt;
            font-weight: bold;
            margin-top: 0;
            margin-bottom: 0.5em;
            border-bottom: 3px solid #4a5568;
            padding-bottom: 0.3em;
        }
        h2 {
            color: #2d3748;
            font-size: 18pt;
            font-weight: bold;
            margin-top: 1.5em;
            margin-bottom: 0.5em;
            border-bottom: 2px solid #718096;
            padding-bottom: 0.2em;
        }
        h3 {
            color: #4a5568;
            font-size: 14pt;
            font-weight: bold;
            margin-top: 1em;
            margin-bottom: 0.3em;
        }
        p {
            margin: 0.5em 0;
        }
        ul, ol {
            margin: 0.5em 0;
            padding-left: 1.5em;
        }
        li {
            margin: 0.3em 0;
        }
        strong {
            color: #1a1a1a;
            font-weight: 600;
        }
        em {
            font-style: italic;
            color: #4a5568;
        }
        hr {
            border: none;
            border-top: 1px solid #cbd5e0;
            margin: 1.5em 0;
        }
        a {
            color: #2563eb;
            text-decoration: underline;
            font-weight: 500;
        }
        a:hover {
            color: #1d4ed8;
        }
        code {
            background-color: #f7fafc;
            padding: 0.2em 0.4em;
            border-radius: 3px;
            font-family: "Courier New", monospace;
            font-size: 10pt;
        }
    """)

    # Wrap HTML with proper structure
    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>SAM.gov Daily Intelligence Brief</title>
    </head>
    <body>
        {html_content}
    </body>
    </html>
    """

    # Generate PDF
    if output_stream is None:
        output_stream = BytesIO()

    HTML(string=full_html).write_pdf(output_stream, stylesheets=[css])
    output_stream.seek(0)

    return output_stream


async def generate_daily_summary(opportunities, pulled_at, resource_results, date_folder):
    """
    Generate a comprehensive daily summary report using LLM analysis.

    Args:
        opportunities: List of all opportunity records
        pulled_at: Timestamp of the pull
        resource_results: Dict mapping notice_id to list of downloaded file artifact IDs
        date_folder: Date string for folder organization (format: pull_YYYYMMDD)

    Returns:
        Dict with uploaded file paths: {'md': object_key, 'pdf': object_key}
        or None if no matches
    """
    # Filter NAICS-matched opportunities
    matched_opportunities = [opp for opp in opportunities if opp.get("_naics_match")]

    if not matched_opportunities:
        print("  No NAICS-matched opportunities to summarize")
        return None

    print(f"\nGenerating daily summary for {len(matched_opportunities)} opportunities...")

    # Initialize LLM service
    llm_service = LLMService()
    if not llm_service.is_available:
        print("  ⚠ LLM service not available, skipping summary generation")
        return None

    # Prepare to collect analyzed outputs for executive summary
    analyzed_entries = []
    # Prepare to collect structured headline items
    headline_items = []

    # Build markdown report
    report_lines = [
        "# SAM.gov Daily Opportunity Intelligence Brief",
        "",
        f"**Date**: {pulled_at.strftime('%B %d, %Y')}",
        f"**Prepared for**: Amivero, LLC",
        f"**Source**: SAM.gov (last 24 hours)",
        "",
    ]

    # Analyze each opportunity
    for idx, opp in enumerate(matched_opportunities, 1):
        notice_id = opp.get("noticeId", "Unknown")
        title = opp.get("title", "Untitled")
        solicitation_number = opp.get("solicitationNumber", "N/A")

        print(f"  Analyzing {idx}/{len(matched_opportunities)}: {solicitation_number}")

        # Add opportunity header (as specified in instructions)
        agency, component = resolve_agency_component(opp)
        report_lines.extend([
            f"### {idx}. {title}",
            "",
            f"**Solicitation Number**: {solicitation_number}",
            f"**Notice ID**: {notice_id}",
            f"**Agency**: {agency} / {component}",
            f"**Posted Date**: {opp.get('postedDate', 'Unknown')}",
            f"**Response Deadline**: {opp.get('responseDeadLine', 'Not specified')}",
        ])

        # Get LLM analysis
        analysis = await analyze_opportunity_with_llm(opp, llm_service)
        if analysis:
            analyzed_entries.append(analysis)

            # Classify for executive summary headline list
            headline_category = classify_headline_opportunity(analysis or "")
            if headline_category and opp.get("uiLink"):
                headline_items.append({
                    "category": headline_category,
                    "title": title,
                    "agency": agency,
                    "component": component,
                    "link": opp["uiLink"],
                })

            report_lines.append("")
            report_lines.append(analysis)
            report_lines.append("")
        else:
            report_lines.extend([
                "",
                "*LLM analysis unavailable*",
                "",
            ])

        # Add explicit links section after LLM analysis
        if "uiLink" in opp:
            report_lines.extend([
                "**Links & Artifacts**:",
                f"- [View on SAM.gov]({opp['uiLink']})",
            ])

        # Add additional info link if available
        if "_full_description" in opp and isinstance(opp["_full_description"], dict):
            additional_info = opp["_full_description"].get("additionalInfoLink")
            if additional_info:
                report_lines.append(f"- [Additional Information]({additional_info})")

        if notice_id in resource_results and resource_results[notice_id]:
            report_lines.append(f"- Supporting documents stored under `{solicitation_number}/`")

        report_lines.append("")

        # Add error info if present
        if "_errors" in opp:
            report_lines.extend([
                "**⚠️ Errors**:",
                "",
            ])
            for error in opp["_errors"]:
                report_lines.append(f"- {error['field']}: {error['message']}")
            report_lines.append("")

        report_lines.append("---")
        report_lines.append("")

    # Generate executive summary using LLM, passing headline_items
    exec_summary = await generate_executive_summary(analyzed_entries, headline_items, llm_service)

    # Insert executive summary at correct location
    report_lines = (
        report_lines[:5] +
        [
            "## Executive Summary",
            "",
            exec_summary if exec_summary else "*Executive summary unavailable*",
            "",
            "---",
            "",
            "## Detailed Opportunity Assessments",
            "",
        ] +
        report_lines[5:]
    )

    # Add footer
    report_lines.extend([
        "",
        f"*Generated by Curatore SAM.gov Integration*  ",
        f"*Target NAICS Codes: {', '.join(sorted(TARGET_NAICS_CODES))}*",
    ])

    # Join into single markdown document
    markdown_content = "\n".join(report_lines)

    # Upload markdown and PDF directly to MinIO (date-based folder structure)
    from minio import Minio

    # Initialize MinIO client for direct upload
    minio_client = Minio(
        "localhost:9000",
        access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        secure=False
    )
    bucket = os.getenv("MINIO_BUCKET_UPLOADS", "curatore-uploads")

    # Ensure bucket exists
    if not minio_client.bucket_exists(bucket):
        minio_client.make_bucket(bucket)

    try:
        # Extract date from date_folder which is "pull_YYYYMMDD"
        date_str = date_folder.replace("pull_", "")
        base_filename = f"sam_pull_summary_{date_str}"
        md_filename = f"{base_filename}.md"
        pdf_filename = f"{base_filename}.pdf"

        results = {}

        # Upload markdown file directly to MinIO
        md_bytes = markdown_content.encode('utf-8')
        md_object_key = f"{DEFAULT_ORG_ID}/sam/{date_folder}/{md_filename}"

        try:
            minio_client.put_object(
                bucket_name=bucket,
                object_name=md_object_key,
                data=BytesIO(md_bytes),
                length=len(md_bytes),
                content_type="text/markdown",
                metadata={
                    "source": "sam.gov",
                    "type": "daily_summary",
                    "format": "markdown",
                    "generated_at": pulled_at.isoformat(),
                    "opportunity_count": str(len(matched_opportunities)),
                }
            )
            results['md'] = md_object_key
            print(f"  ✓ Uploaded markdown: {md_filename}")
            print(f"      Path: {bucket}/{md_object_key}")
        except Exception as md_error:
            print(f"  ✗ Failed to upload markdown: {md_error}")
            # Continue to try PDF upload even if markdown fails

        # Generate and upload PDF (optional - skip if dependencies not available)
        if not PDF_AVAILABLE:
            print(f"  ⚠ PDF generation skipped: System dependencies not installed")
            print(f"    To enable PDF generation:")
            print(f"      brew install pango cairo gdk-pixbuf libffi")
            print(f"      pip install --force-reinstall weasyprint")
        else:
            try:
                pdf_stream = markdown_to_pdf(markdown_content)
                pdf_bytes = pdf_stream.getvalue()
                pdf_object_key = f"{DEFAULT_ORG_ID}/sam/{date_folder}/{pdf_filename}"

                minio_client.put_object(
                    bucket_name=bucket,
                    object_name=pdf_object_key,
                    data=BytesIO(pdf_bytes),
                    length=len(pdf_bytes),
                    content_type="application/pdf",
                    metadata={
                        "source": "sam.gov",
                        "type": "daily_summary",
                        "format": "pdf",
                        "generated_at": pulled_at.isoformat(),
                        "opportunity_count": str(len(matched_opportunities)),
                    }
                )
                results['pdf'] = pdf_object_key
                print(f"  ✓ Uploaded PDF: {pdf_filename}")
                print(f"      Path: {bucket}/{pdf_object_key}")

            except Exception as e:
                print(f"  ⚠ PDF generation/upload failed: {e}")
                # Continue even if PDF fails - we have markdown

        print(f"✓ Daily summary generated in sam/{date_folder}/")
        return results

    except Exception as e:
        print(f"✗ Failed to upload summary: {e}")
        return None


async def write_output(opportunities, pulled_at, date_folder):
    """
    Write JSON output directly to MinIO with date-based folder structure.

    Uploads to object storage with custom path organization:
        {org_id}/sam/{date_folder}/sam_pull_{date}.json

    Args:
        opportunities: List of opportunity records from SAM.gov
        pulled_at: Timestamp of when opportunities were pulled
        date_folder: Date string for folder organization (format: pull_YYYYMMDD)

    Returns:
        str: Object key (path) where file was stored

    Raises:
        RuntimeError: If upload fails
    """

    # Fetch descriptions for NAICS-matched opportunities only
    print("  Fetching descriptions for NAICS-matched opportunities...")
    description_errors = 0
    description_fetched = 0
    for opp in opportunities:
        # Only fetch descriptions for NAICS-matched opportunities
        if not opp.get("_naics_match"):
            continue

        description_url = opp.get("description")
        if description_url:
            description_data, error = fetch_opportunity_description(description_url)
            if description_data:
                opp["_full_description"] = description_data
                description_fetched += 1
            elif error:
                # Add error to opportunity record
                if "_errors" not in opp:
                    opp["_errors"] = []
                opp["_errors"].append({
                    "field": "description",
                    "message": error
                })
                description_errors += 1

    if description_errors > 0:
        print(f"  ✓ Fetched {description_fetched} descriptions ({description_errors} not found)")
    else:
        print(f"  ✓ Fetched {description_fetched} descriptions")

    # Build output JSON
    matched_count = sum(1 for o in opportunities if o.get("_naics_match"))

    output = {
        "metadata": {
            "pulled_at_utc": pulled_at.isoformat(),
            "source": "SAM.gov Opportunities API",
            "date": POSTED_FROM,
            "record_count": len(opportunities),
            "naics_matched_count": matched_count,
            "target_naics_codes": sorted(TARGET_NAICS_CODES),
        },
        "opportunities": opportunities,
    }

    # Generate filename (extract date from date_folder which is "pull_YYYYMMDD")
    date_str = date_folder.replace("pull_", "")
    filename = f"sam_pull_{date_str}.json"

    # Convert JSON to bytes
    json_bytes = json.dumps(output, indent=2, ensure_ascii=False).encode('utf-8')

    # Upload directly to MinIO with date-based folder structure
    from minio import Minio

    minio_client = Minio(
        "localhost:9000",
        access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        secure=False
    )
    bucket = os.getenv("MINIO_BUCKET_UPLOADS", "curatore-uploads")

    # Ensure bucket exists
    if not minio_client.bucket_exists(bucket):
        minio_client.make_bucket(bucket)

    # Build path: {org_id}/sam/{date_folder}/{filename}
    object_key = f"{DEFAULT_ORG_ID}/sam/{date_folder}/{filename}"

    try:
        print(f"Uploading {filename} directly to MinIO...")
        minio_client.put_object(
            bucket_name=bucket,
            object_name=object_key,
            data=BytesIO(json_bytes),
            length=len(json_bytes),
            content_type="application/json",
            metadata={
                "source": "sam.gov",
                "type": "daily_extract",
                "pulled_at": pulled_at.isoformat(),
                "record_count": str(len(opportunities)),
                "naics_matched_count": str(matched_count),
                "target_naics_codes": ",".join(sorted(TARGET_NAICS_CODES)),
                "date": POSTED_FROM,
            }
        )
        print(f"✓ Upload successful")
        print(f"  Path: {bucket}/{object_key}")

        # TODO: API Rate Limit Handling
        # SAM.gov API has limits: 1000 requests/hour, 10 requests/second
        #
        # When native SAM.gov integration is implemented, consider:
        # 1. Track API usage in database (requests per hour)
        # 2. Queue remaining opportunities for later processing
        # 3. Create follow-up jobs for descriptions/resources that hit rate limits
        # 4. Implement exponential backoff for rate limit errors
        # 5. Store partial results and resume on next run
        #
        # For now, all data is fetched in a single run. If rate limits are hit,
        # the script will fail and can be re-run after the rate limit window resets.

        return object_key

    except Exception as e:
        raise RuntimeError(f"Failed to upload to MinIO: {e}")


async def main():
    """
    Main entry point for SAM.gov data pull.

    Fetches opportunities from SAM.gov API and stores them in MinIO object storage
    with database artifact tracking for frontend visibility.
    """
    print("=" * 80)
    print("SAM.gov DHS Opportunities Pull")
    print("=" * 80)
    print(f"Date range: {POSTED_FROM} to {POSTED_TO}")
    print(f"Target agencies: {', '.join(DHS_AGENCIES)}")
    print(f"Notice types: {', '.join(NOTICE_TYPES)}")
    print()

    try:
        # Fetch opportunities from SAM.gov
        print("Fetching opportunities from SAM.gov API...")
        opportunities = fetch_opportunities()
        print(f"✓ Found {len(opportunities)} matching opportunities")
        print()

        if len(opportunities) == 0:
            print("No new opportunities found. Exiting.")
            return

        # Tag records with target NAICS codes
        for opp in opportunities:
            naics_codes = set(opp.get("naicsCodes") or [])
            opp["_naics_match"] = bool(naics_codes & TARGET_NAICS_CODES)

        # Count NAICS matches
        naics_matched_count = sum(1 for opp in opportunities if opp.get("_naics_match"))
        print(f"✓ NAICS filter: {naics_matched_count} of {len(opportunities)} opportunities match target NAICS codes")
        if naics_matched_count > 0:
            print(f"  Target NAICS codes: {', '.join(sorted(TARGET_NAICS_CODES))}")
        print()

        # Get timestamp for all uploads
        pulled_at = datetime.now(timezone.utc)
        date_folder = f"pull_{pulled_at.strftime('%Y%m%d')}"

        # Upload consolidated JSON file directly to MinIO with date-based folder
        print("Uploading consolidated JSON to object storage...")
        json_object_key = await write_output(opportunities, pulled_at, date_folder)
        print()

        # Download resource files for NAICS-matched opportunities
        resource_results = {}
        total_files_downloaded = 0
        if naics_matched_count > 0:
            resource_results = await download_resource_links(opportunities, pulled_at)
            total_files_downloaded = sum(len(artifacts) for artifacts in resource_results.values())
            if total_files_downloaded > 0:
                print(f"\n✓ Downloaded {total_files_downloaded} files from {len(resource_results)} opportunities")
            print()

        # Generate daily summary report with LLM analysis
        summary_result = None
        if naics_matched_count > 0:
            summary_result = await generate_daily_summary(opportunities, pulled_at, resource_results, date_folder)

        # Summary
        print("=" * 80)
        print("SUCCESS")
        print("=" * 80)
        print(f"Saved {len(opportunities)} opportunities")
        print(f"  - {naics_matched_count} match target NAICS codes")
        print()
        print("Consolidated JSON file:")
        print(f"  Path: {json_object_key}")
        print(f"  Includes full descriptions for all NAICS-matched opportunities")
        print()
        if total_files_downloaded > 0:
            print(f"Resource files:")
            print(f"  Downloaded: {total_files_downloaded} files from {len(resource_results)} opportunities")
            print(f"  All files organized by solicitation number")
            print()
        if summary_result:
            print(f"Daily Summary Reports:")
            if 'md' in summary_result:
                print(f"  Markdown Report:")
                print(f"    Path: {summary_result['md']}")
            if 'pdf' in summary_result:
                print(f"  PDF Report:")
                print(f"    Path: {summary_result['pdf']}")
            print(f"  AI-powered analysis of {naics_matched_count} opportunities")
            print()
        print(f"Organization: {DEFAULT_ORG_ID}")
        print()
        print("Date-based folder structure:")
        print(f"  {DEFAULT_ORG_ID}/sam/{date_folder}/")

        # Extract date portion for display (remove "pull_" prefix)
        date_str = date_folder.replace("pull_", "")
        print(f"    ├── sam_pull_{date_str}.json")
        print(f"    ├── sam_pull_summary_{date_str}.md")
        print(f"    └── sam_pull_summary_{date_str}.pdf")
        print()
        print("View in frontend:")
        print(f"  http://localhost:3000/storage")
        print(f"  Navigate to: Default Storage > {DEFAULT_ORG_ID} > sam/ > {date_folder}/")
        print()
        print("View in MinIO Console:")
        print(f"  http://localhost:9001")
        print(f"  Login: minioadmin/minioadmin")
        print(f"  Browse: curatore-uploads/{DEFAULT_ORG_ID}/sam/{date_folder}/")
        print()

    except Exception as e:
        print()
        print("=" * 80)
        print("ERROR")
        print("=" * 80)
        print(f"Failed to complete SAM.gov pull: {e}")
        print()
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    asyncio.run(main())
