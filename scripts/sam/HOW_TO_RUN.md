# How to Run SAM.gov Pull Script

Quick reference guide for running `scripts/sam/sam_pull.py`

---

## ✅ Prerequisites

Before running the script, ensure:

1. **Services are running:**
   ```bash
   ./scripts/dev-up.sh
   ```

2. **Storage is initialized:**
   ```bash
   ./scripts/init_storage.sh
   ```

3. **Environment configured:**
   - Check `.env` file has:
     - `SAM_API_KEY=your-api-key`
     - `DEFAULT_ORG_ID=your-org-uuid`

---

## 🚀 Method 1: Docker (EASIEST - Recommended for First Run)

**No Python installation needed!**

```bash
# Run once
docker-compose exec backend python /app/scripts/sam/sam_pull.py

# Run in background
docker-compose exec -T backend python /app/scripts/sam/sam_pull.py &
```

**Pros:**
- ✅ No local Python setup required
- ✅ All dependencies already installed in container
- ✅ Same environment as backend service

**Cons:**
- ❌ Requires Docker services to be running
- ❌ Slightly slower startup

---

## 🐍 Method 2: Backend Virtual Environment (Best for Development)

**Use the existing backend Python environment:**

```bash
# Activate backend venv
cd backend
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate    # Windows

# Return to project root
cd ..

# Run script
python scripts/sam/sam_pull.py

# Deactivate when done (optional)
deactivate
```

**Pros:**
- ✅ Fast execution
- ✅ Uses same dependencies as backend
- ✅ No additional setup

**Cons:**
- ❌ Requires backend venv to exist
- ❌ Must activate venv first

---

## 🆕 Method 3: New Virtual Environment (If Backend venv Not Available)

**Create a dedicated environment for scripts:**

```bash
# One-time setup
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# venv\Scripts\activate    # Windows
pip install -r backend/requirements.txt

# Run script
python scripts/sam/sam_pull.py

# Deactivate when done
deactivate
```

**Pros:**
- ✅ Independent from backend
- ✅ Clean environment

**Cons:**
- ❌ Requires initial setup
- ❌ Duplicates dependencies

---

## 📅 Scheduling with Cron

### Using Backend Virtual Environment

```bash
crontab -e
```

Add this line for daily 6 AM runs:
```cron
0 6 * * * cd /Users/davidlarrimore/Documents/Github/curatore-v2 && source backend/venv/bin/activate && python scripts/sam/sam_pull.py >> logs/sam_pull.log 2>&1
```

### Using Docker

```bash
crontab -e
```

Add this line for daily 6 AM runs:
```cron
0 6 * * * cd /Users/davidlarrimore/Documents/Github/curatore-v2 && docker-compose exec -T backend python /app/scripts/sam/sam_pull.py >> logs/sam_pull.log 2>&1
```

**Create logs directory:**
```bash
mkdir -p logs
```

---

## 🔍 Troubleshooting

### "command not found: python"

**Solution 1:** Use `python3` instead:
```bash
python3 scripts/sam/sam_pull.py
```

**Solution 2:** Create alias in `~/.zshrc` or `~/.bashrc`:
```bash
echo "alias python=python3" >> ~/.zshrc
source ~/.zshrc
```

**Solution 3:** Use Docker method (no Python needed)

### "No module named 'app'"

**Cause:** Virtual environment not activated

**Solution:** Activate venv first:
```bash
cd backend
source venv/bin/activate
cd ..
python scripts/sam/sam_pull.py
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

### "Connection refused"

**Cause:** Services not running

**Solution:**
```bash
./scripts/dev-up.sh
# Wait for services to start (30 seconds)
./scripts/init_storage.sh
```

---

## 📊 Verify Success

After running the script, check results:

1. **Console Output:**
   ```
   ================================================================================
   SUCCESS
   ================================================================================
   Saved 10 opportunities
   Storage location: curatore-uploads/org-uuid/rfi/sam_dhs_opportunities_...
   ```

2. **Frontend:**
   - Visit: http://localhost:3000/storage
   - Navigate: Default Storage > {org_id} > rfi/
   - You should see the JSON file

3. **MinIO Console:**
   - Visit: http://localhost:9001
   - Login: admin/changeme
   - Browse: curatore-uploads/{org_id}/rfi/

4. **Database:**
   ```bash
   # Check artifact records
   docker-compose exec backend python -c "
   from app.services.database_service import database_service
   from app.database.models import Artifact
   from sqlalchemy import select
   import asyncio

   async def check():
       async with database_service.get_session() as session:
           result = await session.execute(select(Artifact).limit(5))
           artifacts = result.scalars().all()
           print(f'Found {len(artifacts)} artifacts')
           for a in artifacts:
               print(f'  - {a.original_filename}')

   asyncio.run(check())
   "
   ```

---

## 🎯 Quick Command Reference

```bash
# Check if services are running
docker-compose ps

# View backend logs
./scripts/dev-logs.sh backend

# Check queue health
./scripts/queue_health.sh

# Test MinIO connection
curl http://localhost:9001/minio/health/live

# Run script via Docker (recommended)
docker-compose exec backend python /app/scripts/sam/sam_pull.py

# Run script via venv
cd backend && source venv/bin/activate && cd .. && python scripts/sam/sam_pull.py
```

---

## 💡 Pro Tips

1. **First time?** Use Docker method - it's the most reliable
2. **Development?** Use backend venv - it's the fastest
3. **Production?** Use cron + Docker - it's the most reliable for automation
4. **Testing?** Add `--dry-run` flag support (future enhancement)

---

**For detailed documentation, see:** `scripts/sam/README.md`
