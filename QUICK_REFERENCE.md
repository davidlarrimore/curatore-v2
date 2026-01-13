# Curatore v2 - Quick Reference Card

**Phase**: 2 Complete ✅ | **Next**: Phase 3
**Date**: January 12, 2026

---

## 🚀 Quick Start

```bash
# Start all services
./scripts/dev-up.sh

# Check health
curl http://localhost:8000/api/v1/system/health/database | jq .
open http://localhost:3000/health

# Stop services
./scripts/dev-down.sh
```

---

## 🔐 Credentials

### Admin Account
```
Email:    admin@example.com
Username: admin
Password: changeme
Role:     org_admin
```

### Test User
```
Email:    testuser@example.com
Username: testuser
Password: SecurePass123
Role:     member
```

---

## 📡 Key Endpoints

### Authentication
```bash
# Login
POST /api/v1/auth/login
Body: {"email_or_username": "admin@example.com", "password": "changeme"}

# Get profile
GET /api/v1/auth/me
Header: Authorization: Bearer <token>

# Register
POST /api/v1/auth/register
Body: {"email": "...", "username": "...", "password": "..."}

# Refresh token
POST /api/v1/auth/refresh
Body: {"refresh_token": "..."}
```

### Health Checks
```bash
GET /api/v1/system/health/comprehensive    # All components
GET /api/v1/system/health/backend          # Backend API
GET /api/v1/system/health/database         # Database (enhanced!)
GET /api/v1/system/health/redis            # Redis
GET /api/v1/system/health/celery           # Worker
```

---

## 🔧 Common Commands

### Database
```bash
# Reseed database
docker exec curatore-backend python -m app.commands.seed --create-admin

# Generate migration
docker exec -w /app curatore-backend alembic revision --autogenerate -m "Description"

# Apply migrations
docker exec -w /app curatore-backend alembic upgrade head

# Check current revision
docker exec -w /app curatore-backend alembic current
```

### Docker
```bash
# View logs
./scripts/dev-logs.sh backend
./scripts/dev-logs.sh worker
docker logs -f curatore-backend

# Rebuild services
docker-compose build backend worker
docker-compose up -d backend worker

# Shell into container
docker exec -it curatore-backend bash

# Clean up
./scripts/dev-down.sh
./scripts/clean.sh
```

---

## 📊 Database Info

**Type**: SQLite (development)
**Location**: `./data/curatore.db`
**URL**: `sqlite+aiosqlite:///./data/curatore.db`

**Tables**:
- organizations (1 row)
- users (2 rows)
- api_keys (0 rows)
- connections (0 rows)
- system_settings (0 rows)
- audit_logs (0 rows)

---

## 🎯 Phase 3 TODO

### High Priority
- [ ] Organization management endpoints
- [ ] User management endpoints (invite, update, deactivate)
- [ ] API key management endpoints (generate, revoke, list)

### Medium Priority
- [ ] Connection management (LLM, SharePoint config in DB)
- [ ] Multi-tenant query isolation (add org filters)
- [ ] Audit logging

### Low Priority
- [ ] Migration script from ENV to DB
- [ ] Email verification
- [ ] Password reset

---

## 🐛 Troubleshooting

### Service won't start
```bash
docker-compose down
docker-compose up -d
docker logs curatore-backend
```

### Database issues
```bash
# Recreate database
rm data/curatore.db
docker-compose restart backend
docker exec curatore-backend python -m app.commands.seed --create-admin
```

### Authentication not working
```bash
# Check JWT secret is set
docker exec curatore-backend env | grep JWT_SECRET_KEY

# Test login directly
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email_or_username":"admin@example.com","password":"changeme"}'
```

---

## 📁 Important Files

**Checkpoint**: `CHECKPOINT_PHASE2_COMPLETE.md` (full details)
**Plan**: `plan.md` (overall roadmap)
**Docs**: `CLAUDE.md` (development guide)
**Config**: `.env.example` (environment variables)

---

## 🌐 URLs

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Health Dashboard**: http://localhost:3000/health

---

**Quick tip**: If you forget credentials, check `CHECKPOINT_PHASE2_COMPLETE.md` section "Authentication Credentials"
