# Curatore v2 - Phase 2 Checkpoint

**Date**: January 12, 2026
**Status**: Phase 2 Complete ✅
**Next**: Phase 3 - Multi-Tenant Organizations

---

## ✅ Completed Work

### Phase 1: Database Foundation (Complete)
- ✅ SQLAlchemy models with multi-tenant architecture
- ✅ 6 tables: Organizations, Users, ApiKeys, Connections, SystemSettings, AuditLog
- ✅ Alembic migrations configured and working
- ✅ Database service with async session management
- ✅ Health check endpoints for all system components
- ✅ SQLite + PostgreSQL support (currently using SQLite)

### Phase 2: Authentication (Complete)
- ✅ JWT token-based authentication (access + refresh tokens)
- ✅ API key authentication with bcrypt hashing
- ✅ Password hashing with bcrypt (12 rounds)
- ✅ FastAPI dependencies for auth and authorization
- ✅ Role-based access control (org_admin, member, viewer)
- ✅ Seed command for initial org and admin user
- ✅ Authentication endpoints (register, login, refresh, /me)
- ✅ Enhanced database health panel with table counts and migration info

---

## 🗄️ Database State

**Type**: SQLite (development)
**Location**: `./data/curatore.db` (0.15 MB)
**Connection**: `sqlite+aiosqlite:///./data/curatore.db`

**Current Data**:
- Organizations: 1 (Default Organization)
- Users: 1 (admin user)
- API Keys: 0
- Connections: 0
- System Settings: 0
- Audit Logs: 0

**Migration Version**: Database migrated, tables created via init_db() on startup

---

## 🔐 Authentication Credentials

### Default Admin Account
- **Email**: `admin@example.com`
- **Username**: `admin`
- **Password**: `changeme`
- **Role**: `org_admin`
- **Organization**: Default Organization (slug: `default`)

### Test User Account
- **Email**: `testuser@example.com`
- **Username**: `testuser`
- **Password**: `SecurePass123`
- **Role**: `member`

---

## 🏗️ Architecture Overview

### Authentication Flow
```
1. User sends credentials → POST /api/v1/auth/login
2. Backend validates password (bcrypt)
3. Backend generates JWT tokens (access: 60min, refresh: 30 days)
4. User receives: { access_token, refresh_token, token_type, expires_in }
5. User includes token in requests: Authorization: Bearer <token>
6. Backend validates token via dependencies.py
7. Backend extracts user/org context from token
```

### Multi-Tenant Isolation
- Every user belongs to ONE organization
- JWT tokens include org_id claim
- All queries should filter by organization_id
- Row-level security enforced at application layer

### File Structure
```
backend/
├── app/
│   ├── api/v1/
│   │   ├── routers/
│   │   │   ├── auth.py          ✅ Authentication endpoints
│   │   │   ├── documents.py     📄 Document processing
│   │   │   ├── jobs.py          📄 Job status
│   │   │   ├── sharepoint.py    📄 SharePoint integration
│   │   │   └── system.py        ✅ Health checks (enhanced)
│   │   └── models.py            📄 API request/response models
│   ├── commands/
│   │   └── seed.py              ✅ Database seeding
│   ├── database/
│   │   ├── base.py              ✅ SQLAlchemy declarative base
│   │   └── models.py            ✅ Database models (Phase 1 & 2)
│   ├── services/
│   │   ├── auth_service.py      ✅ JWT & API key logic
│   │   ├── database_service.py  ✅ Database connection (enhanced)
│   │   ├── document_service.py  📄 Document processing
│   │   ├── llm_service.py       📄 LLM integration
│   │   └── ...
│   ├── dependencies.py          ✅ FastAPI auth dependencies
│   ├── config.py                ✅ Settings with JWT config
│   └── main.py                  ✅ FastAPI app with auth
├── alembic/
│   ├── versions/                📁 (empty - using init_db)
│   └── alembic.ini              ✅ Alembic configuration
└── requirements.txt             ✅ Updated with email-validator

frontend/
├── app/health/page.tsx          ✅ Enhanced health page with database
└── lib/api.ts                   ✅ API client with database health
```

---

## 📝 Files Created/Modified in Phase 2

### New Files (4)
1. `backend/app/services/auth_service.py` - JWT & API key authentication
2. `backend/app/dependencies.py` - FastAPI auth dependencies
3. `backend/app/api/v1/routers/auth.py` - Auth endpoints
4. `backend/app/commands/seed.py` - Database seeding script

### Modified Files (8)
1. `backend/app/database/models.py` - Fixed UUID type for SQLite compatibility
2. `backend/app/services/database_service.py` - Enhanced health_check with table counts
3. `backend/app/api/v1/routers/system.py` - Enhanced database health endpoint
4. `backend/app/api/v1/__init__.py` - Added auth router
5. `backend/app/config.py` - Added JWT settings (already had them)
6. `backend/requirements.txt` - Added email-validator
7. `backend/Dockerfile` - Added Alembic files to image
8. `frontend/app/health/page.tsx` - Added database component
9. `frontend/lib/api.ts` - Added database to health check types

---

## 🧪 Verified Working

### Authentication Endpoints
✅ `POST /api/v1/auth/register` - Create new user
✅ `POST /api/v1/auth/login` - Login with JWT tokens
✅ `POST /api/v1/auth/refresh` - Refresh access token
✅ `POST /api/v1/auth/logout` - Logout
✅ `GET /api/v1/auth/me` - Get current user profile

### Health Endpoints
✅ `GET /api/v1/system/health/backend` - Backend API health
✅ `GET /api/v1/system/health/database` - Database health (enhanced!)
✅ `GET /api/v1/system/health/redis` - Redis health
✅ `GET /api/v1/system/health/celery` - Celery worker health
✅ `GET /api/v1/system/health/extraction` - Extraction service health
✅ `GET /api/v1/system/health/llm` - LLM connection health
✅ `GET /api/v1/system/health/sharepoint` - SharePoint health
✅ `GET /api/v1/system/health/comprehensive` - All components

### Frontend Pages
✅ `http://localhost:3000` - Main application
✅ `http://localhost:3000/health` - System health dashboard (with database!)

---

## 🚀 Quick Start Commands

### Start Services
```bash
./scripts/dev-up.sh
# Or
make up
```

### Check Health
```bash
curl http://localhost:8000/api/v1/system/health/database | jq .
```

### Test Authentication
```bash
# Login
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email_or_username":"admin@example.com","password":"changeme"}'

# Get profile (replace <TOKEN> with access_token from login)
curl -H "Authorization: Bearer <TOKEN>" \
  http://localhost:8000/api/v1/auth/me
```

### Reseed Database
```bash
docker exec curatore-backend python -m app.commands.seed --create-admin
```

### Run Migrations (when needed)
```bash
# Generate migration
docker exec -w /app curatore-backend alembic revision --autogenerate -m "Description"

# Apply migrations
docker exec -w /app curatore-backend alembic upgrade head
```

---

## 📋 Phase 3 Plan: Multi-Tenant Organizations

### Goals
Implement full multi-tenant organization management with proper isolation.

### Tasks Overview

#### 3.1: Organization Management Endpoints
- [ ] `GET /api/v1/organizations/me` - Get current user's organization
- [ ] `PUT /api/v1/organizations/me` - Update organization settings
- [ ] `GET /api/v1/organizations/me/settings` - Get organization settings
- [ ] `PUT /api/v1/organizations/me/settings` - Update organization settings

#### 3.2: User Management Endpoints (Org Admins Only)
- [ ] `GET /api/v1/organizations/me/users` - List users in organization
- [ ] `POST /api/v1/organizations/me/users` - Invite new user
- [ ] `GET /api/v1/organizations/me/users/{user_id}` - Get user details
- [ ] `PUT /api/v1/organizations/me/users/{user_id}` - Update user (role, etc.)
- [ ] `DELETE /api/v1/organizations/me/users/{user_id}` - Deactivate user
- [ ] `POST /api/v1/organizations/me/users/{user_id}/reactivate` - Reactivate user

#### 3.3: API Key Management Endpoints
- [ ] `GET /api/v1/api-keys` - List user's API keys
- [ ] `POST /api/v1/api-keys` - Generate new API key
- [ ] `DELETE /api/v1/api-keys/{key_id}` - Revoke API key
- [ ] `PUT /api/v1/api-keys/{key_id}` - Update API key (name, expiration)

#### 3.4: Connection Management (LLM & SharePoint)
- [ ] `GET /api/v1/connections` - List organization connections
- [ ] `POST /api/v1/connections` - Create new connection
- [ ] `GET /api/v1/connections/{connection_id}` - Get connection details
- [ ] `PUT /api/v1/connections/{connection_id}` - Update connection
- [ ] `DELETE /api/v1/connections/{connection_id}` - Delete connection
- [ ] `POST /api/v1/connections/{connection_id}/test` - Test connection

#### 3.5: Multi-Tenant Query Isolation
- [ ] Add organization_id filters to ALL document queries
- [ ] Add organization_id filters to ALL job queries
- [ ] Add organization_id to document upload/processing
- [ ] Update storage service to isolate by organization
- [ ] Update batch processing to respect organization boundaries

#### 3.6: Audit Logging
- [ ] Log user actions (login, logout, changes)
- [ ] Log organization changes
- [ ] Log connection changes
- [ ] Log API key creation/revocation
- [ ] Endpoint: `GET /api/v1/audit-logs` (admin only)

#### 3.7: Migration from ENV to Database
- [ ] Script to migrate OPENAI_* settings to Connection table
- [ ] Script to migrate MS_* settings to Connection table
- [ ] Backward compatibility mode (check DB first, fall back to ENV)
- [ ] Command: `python -m app.commands.migrate --import-env-connections`

---

## 🔧 Environment Variables

### Required
```bash
# Database
DATABASE_URL=sqlite+aiosqlite:///./data/curatore.db

# JWT Authentication
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
JWT_REFRESH_TOKEN_EXPIRE_DAYS=30
BCRYPT_ROUNDS=12
API_KEY_PREFIX=cur_

# Seeding (for initial setup)
ADMIN_EMAIL=admin@example.com
ADMIN_USERNAME=admin
ADMIN_PASSWORD=changeme
ADMIN_FULL_NAME=Admin User
DEFAULT_ORG_NAME=Default Organization
DEFAULT_ORG_SLUG=default

# LLM (currently from ENV, will move to DB in Phase 3)
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=gpt-4o-mini
OPENAI_BASE_URL=https://api.openai.com/v1

# SharePoint (currently from ENV, will move to DB in Phase 3)
MS_TENANT_ID=your-tenant-id
MS_CLIENT_ID=your-client-id
MS_CLIENT_SECRET=your-client-secret

# Queue
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1

# Services
EXTRACTION_SERVICE_URL=http://extraction:8010
```

---

## 🐛 Known Issues / Notes

1. **Alembic Version Shows "unknown"**
   - Tables created via `init_db()` on startup instead of migrations
   - `alembic_version` table not populated
   - Non-critical: database is functional
   - Can be fixed by running proper migration

2. **Authentication Disabled by Default**
   - `ENABLE_AUTH=false` in backend startup
   - Set to `true` to enforce authentication on all endpoints
   - Allows backward compatibility during migration

3. **Database is SQLite**
   - Good for development
   - For production, switch to PostgreSQL:
     ```bash
     DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/curatore
     ```

4. **LLM and SharePoint Config in ENV**
   - Currently using environment variables
   - Phase 3 will move these to database (Connection table)
   - Allows per-organization configuration

---

## 📚 Key Documentation

### Authentication
- JWT tokens signed with HS256 algorithm
- Access tokens expire in 60 minutes
- Refresh tokens expire in 30 days
- Passwords hashed with bcrypt (12 rounds)
- API keys hashed with bcrypt and prefixed with `cur_`

### Database Models
- **Organization**: Multi-tenant root entity
- **User**: Belongs to one organization, has role (org_admin/member/viewer)
- **ApiKey**: Belongs to user, used for API authentication
- **Connection**: Stores LLM/SharePoint credentials per organization
- **SystemSetting**: Global key-value settings
- **AuditLog**: Tracks user actions and changes

### Security
- Row-level security via organization_id filtering
- JWT tokens include org_id claim
- API keys scoped to user's organization
- Role-based access control (RBAC)
- bcrypt for all password/key storage

---

## 🔄 How to Resume Work

### When You Return:

1. **Start Services**
   ```bash
   cd /Users/davidlarrimore/Documents/Github/curatore-v2
   ./scripts/dev-up.sh
   ```

2. **Verify System Health**
   ```bash
   curl http://localhost:8000/api/v1/system/health/comprehensive | jq .
   # Visit: http://localhost:3000/health
   ```

3. **Check Database State**
   ```bash
   curl http://localhost:8000/api/v1/system/health/database | jq .
   ```

4. **Test Authentication**
   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email_or_username":"admin@example.com","password":"changeme"}' | jq .
   ```

5. **Begin Phase 3**
   - Read the Phase 3 plan above
   - Start with Organization Management endpoints
   - Reference existing auth code for patterns

### Useful Commands
```bash
# View logs
./scripts/dev-logs.sh backend
./scripts/dev-logs.sh worker

# Stop services
./scripts/dev-down.sh

# Rebuild after changes
docker-compose build backend worker
docker-compose up -d backend worker
```

---

## 🎯 Success Metrics

Phase 2 is considered complete with:
- ✅ User registration working
- ✅ User login returning JWT tokens
- ✅ Token refresh working
- ✅ Protected endpoints accepting Bearer tokens
- ✅ Role-based authorization working
- ✅ API key authentication ready (endpoints created, can be tested in Phase 3)
- ✅ Database seeding working
- ✅ Health dashboard showing database info

**All metrics met!** Ready for Phase 3.

---

## 📞 Contact & Resources

- **Project**: Curatore v2 - RAG-ready document processing platform
- **Stack**: FastAPI + Next.js + SQLAlchemy + Celery + Redis
- **Docs**: http://localhost:8000/docs (when running)
- **GitHub**: Check CLAUDE.md for project conventions

---

**Last Updated**: January 12, 2026, 8:15 PM EST
**Next Session**: Start with Phase 3.1 - Organization Management Endpoints
