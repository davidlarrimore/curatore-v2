# SAM.gov Pull Script - Quick Start

## Run It Now (One Command)

```bash
# Run directly (recommended)
./scripts/sam/run.sh

# Or with bash explicitly
bash scripts/sam/run.sh
```

**⚠️ IMPORTANT**:
- ✅ DO use: `./scripts/sam/run.sh` or `bash scripts/sam/run.sh`
- ❌ DON'T use: `sh scripts/sam/run.sh` (this will fail with an error)

That's it! The script will:
- ✅ Find Python 3.12/3.13 automatically
- ✅ Create/use virtual environment
- ✅ Install dependencies if needed
- ✅ Verify environment variables
- ✅ Run the SAM.gov pull

---

## First Time Setup

If you haven't set up the project yet:

```bash
# 1. Start services
./scripts/dev-up.sh
./scripts/init_storage.sh

# 2. Initialize database (one-time)
cd backend
source venv/bin/activate
python -m app.commands.seed --create-admin
cd ..

# 3. Add to .env file
SAM_API_KEY=your-sam-gov-api-key-here
DEFAULT_ORG_ID=your-org-uuid-from-seed-output

# 4. Run the script
./scripts/sam/run.sh
```

---

## Get SAM.gov API Key

1. Go to https://sam.gov/
2. Register/Login
3. Navigate to: **Data Services** → **API Access**
4. Generate API key
5. Add to `.env`: `SAM_API_KEY=your-key-here`

---

## What It Does

**Fetches:** Last 24 hours of opportunities
**Filters:** DHS agencies (ICE, CBP, USCIS)
**Notice Types:** Sources Sought, Special Notice, Solicitation
**Storage:** MinIO at `{bucket}/{org_id}/rfi/{filename}.json`
**Database:** Creates artifact record for frontend visibility

---

## View Results

**Frontend:**
- URL: http://localhost:3000/storage
- Path: Default Storage → {org_id} → rfi/

**MinIO Console:**
- URL: http://localhost:9001
- Login: admin/changeme
- Path: curatore-uploads/{org_id}/rfi/

---

## Schedule Daily Runs

```bash
crontab -e
# Add this line for daily 6 AM runs:
0 6 * * * cd /path/to/curatore-v2 && ./scripts/sam/run.sh >> logs/sam_pull.log 2>&1
```

Create logs directory:
```bash
mkdir -p logs
```

---

## Troubleshooting

### "Python 3.12 or 3.13 not found"

Install Python 3.12:
```bash
brew install python@3.12
```

### "SAM_API_KEY not set"

Add to `.env` file:
```bash
echo "SAM_API_KEY=your-key-here" >> .env
```

### "DEFAULT_ORG_ID not set"

Run seed command and add output to `.env`:
```bash
cd backend
source venv/bin/activate
python -m app.commands.seed --create-admin
# Copy organization ID from output
cd ..
echo "DEFAULT_ORG_ID=your-org-uuid" >> .env
```

### Services not running

```bash
./scripts/dev-up.sh
./scripts/init_storage.sh
```

---

## Alternative Methods

### Via Docker (no Python setup needed)

```bash
docker-compose exec backend python /app/scripts/sam/sam_pull.py
```

### Via Backend venv

```bash
cd backend
source venv/bin/activate
cd ..
python scripts/sam/sam_pull.py
```

### Via Custom venv

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
python scripts/sam/sam_pull.py
```

---

## Script Details

**Location:** `scripts/sam/run.sh`
**Auto-configures:** Python environment, dependencies, validation
**Requirements:** Python 3.12 or 3.13
**Dependencies:** Installed automatically from `backend/requirements.txt`

---

## Need Help?

- **Full documentation:** `scripts/sam/README.md`
- **Detailed guide:** `scripts/sam/HOW_TO_RUN.md`
- **Script source:** `scripts/sam/sam_pull.py`
- **Configuration:** `.env.review.md`

---

**Status:** ✅ Ready to run with `./scripts/sam/run.sh`
