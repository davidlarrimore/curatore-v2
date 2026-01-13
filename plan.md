# Curatore v2 - System Persistence & Multi-Tenancy Implementation Plan

**Status**: Phase 2 Complete ✅ (Authentication)
**Last Updated**: 2026-01-12
**Progress**: 25% (2 of 8 phases complete)

## Current Status

**✅ COMPLETED: Phase 1 - Database Foundation**
- Database models created (Organizations, Users, ApiKeys, Connections, SystemSettings, AuditLog)
- Database service with async SQLAlchemy session management
- Alembic migrations configured
- Configuration updated (.env.example, config.py)
- Application integration (main.py startup/shutdown)
- Health check endpoints added
- All dependencies installed

**✅ COMPLETED: Phase 2 - Authentication**
- ✅ auth_service.py (JWT + API keys + bcrypt)
- ✅ dependencies.py (FastAPI auth helpers with role-based access)
- ✅ Auth endpoints (login, register, refresh, /me)
- ✅ Seed command for initial org and admin user
- ✅ Enhanced database health panel (table counts, migration version, size)
- ✅ All authentication flows tested and working

**🔄 NEXT: Phase 3 - Multi-Tenant Organizations**
- Organization management endpoints (CRUD)
- User management endpoints (invite, update, deactivate)
- API key management endpoints (generate, revoke, list)
- Connection management endpoints (LLM, SharePoint)
- Multi-tenant query isolation (add org_id filters everywhere)
- Audit logging for all changes

See `CHECKPOINT_PHASE2_COMPLETE.md` for detailed resume instructions and Phase 3 plan.

---

## Overview

Add enterprise-grade persistence, multi-tenant organizations, and authentication to Curatore v2 while maintaining backward compatibility with ENV-based configuration.

## Architecture Decision

**Database**: SQLite (development) + PostgreSQL (production) with SQLAlchemy async ORM
**Authentication**: JWT tokens (frontend users) + API Keys (backend/headless access)
**Multi-Tenancy**: Organizations → Users → Connections hierarchy
**Connection Management**: Runtime-configurable connections for SharePoint, LLM, Extraction services (extensible)

## Data Model

```
Organizations (tenants)
  ├── Users (email, username, password_hash, role)
  ├── ApiKeys (for headless access)
  ├── Connections (polymorphic: SharePoint, LLM, Extraction, future: S3, WebScraper, OpenWebUI)
  └── Settings (org-level defaults)

SystemSettings (global defaults)
AuditLog (track configuration changes)
```

### Key Tables

1. **organizations**: id, name, slug, is_active, settings (JSONB), created_at
2. **users**: id, org_id, email, username, password_hash, role, is_active, settings (JSONB)
3. **api_keys**: id, org_id, user_id, name, key_hash, prefix, scopes, expires_at
4. **connections**: id, org_id, name, connection_type, config (JSONB), is_active, is_default, last_tested_at, test_status
5. **system_settings**: key, value (JSONB), description, is_public
6. **audit_logs**: org_id, user_id, action, entity_type, entity_id, details, status

## Configuration Precedence

Priority order (highest to lowest):
1. **ENV variables** (core backend: FILES_ROOT, CELERY_BROKER_URL - always respected)
2. **User Settings** (user.settings JSON)
3. **Organization Settings** (organization.settings JSON)
4. **System Settings** (system_settings table)
5. **Hard-coded defaults** (config.py)

## Critical Files to Create

### Database & Models
- `backend/app/database/__init__.py`
- `backend/app/database/models.py` - All SQLAlchemy models
- `backend/app/database/base.py` - Base class and session factory
- `backend/alembic.ini` - Alembic configuration
- `backend/alembic/env.py` - Migration environment
- `backend/alembic/versions/001_initial_schema.py` - Initial migration

### Services (Following existing singleton pattern)
- `backend/app/services/database_service.py` - Async session management, health checks
- `backend/app/services/auth_service.py` - JWT tokens, API keys, password hashing (bcrypt)
- `backend/app/services/connection_service.py` - CRUD + test-on-save for connections
- `backend/app/services/audit_log_service.py` - Audit logging

### API Routers (All under /api/v1/)
- `backend/app/api/v1/routers/auth.py` - login, register, refresh, logout, /me
- `backend/app/api/v1/routers/api_keys.py` - CRUD for API keys
- `backend/app/api/v1/routers/organizations.py` - CRUD for organizations
- `backend/app/api/v1/routers/users.py` - CRUD for users
- `backend/app/api/v1/routers/connections.py` - CRUD + test endpoint
- `backend/app/api/v1/routers/settings.py` - Get/update settings with precedence

### Dependencies
- `backend/app/dependencies.py` - FastAPI dependency injection (get_current_user, require_org_admin)

### Commands
- `backend/app/commands/seed.py` - Seed initial org + admin user
- `backend/app/commands/migrate.py` - ENV → DB migration tool

### Frontend
- `frontend/app/login/page.tsx` - Login page
- `frontend/app/connections/page.tsx` - Connection management UI
- `frontend/components/ConnectionManager.tsx` - Connection CRUD component
- `frontend/lib/auth.ts` - JWT token management

## Files to Modify

1. `backend/requirements.txt` - Add SQLAlchemy, Alembic, JWT, bcrypt
2. `backend/app/config.py` - Add DATABASE_URL, JWT settings
3. `backend/app/main.py` - Initialize database, add new routers
4. `backend/app/api/v1/__init__.py` - Include new routers
5. `backend/app/services/document_service.py` - Use connection_service for extraction
6. `backend/app/services/llm_service.py` - Use connection_service for LLM
7. `backend/app/services/sharepoint_service.py` - Use connection_service for SharePoint
8. `.env.example` - Add database, auth, connection settings
9. `frontend/lib/api.ts` - Add JWT token handling
10. `docker-compose.yml` - Add PostgreSQL service (optional)

## Connection Service Design

### Connection Types (Extensible Registry Pattern)

Each connection type implements:
- `validate_config()` - Validate connection configuration
- `test_connection()` - Health check (called on save)
- `get_config_schema()` - JSON schema for frontend

**Built-in types:**
1. **SharePointConnectionType**: tenant_id, client_id, client_secret, folder_url
2. **LLMConnectionType**: api_key, model, base_url, timeout
3. **ExtractionConnectionType**: service_url, api_key, timeout

**Future types** (easy to add):
- S3ConnectionType
- WebScraperConnectionType
- OpenWebUIConnectionType

### Test-on-Save Flow

```python
# POST /api/v1/connections
1. Validate connection type exists
2. Validate configuration (type-specific schema)
3. Save to database
4. Auto-test connection (if AUTO_TEST_CONNECTIONS=true)
5. Update last_tested_at, test_status, test_result
6. Return connection with test results
```

## Authentication Flow

### JWT (Frontend Users)
1. User submits email/password to `POST /api/v1/auth/login`
2. Backend validates credentials, returns access_token + refresh_token
3. Frontend stores tokens, includes in Authorization header: `Bearer <token>`
4. Backend validates JWT on each request via `get_current_user` dependency
5. Token expiration: access (60 min), refresh (30 days)

### API Keys (Backend/Headless)
1. Admin creates API key via `POST /api/v1/api-keys`
2. Backend generates key: `cur_<random32bytes>`, returns ONCE
3. Backend stores bcrypt hash in database
4. Client includes in header: `X-API-Key: cur_...`
5. Backend validates via `get_current_user_from_api_key` dependency

## Implementation Phases

### Phase 1: Database Foundation (Week 1-2)
- Create all SQLAlchemy models
- Setup Alembic migrations
- Create database_service with async session management
- Database health check endpoint
- **Deliverable**: Database initialized, all tables created

### Phase 2: Authentication (Week 3-4)
- Create auth_service (JWT + API keys + bcrypt)
- Create auth endpoints (login, register, refresh, logout)
- Create dependency injection functions
- Seed command for initial admin
- **Deliverable**: Users can login and receive JWT tokens

### Phase 3: Multi-Tenant Organizations (Week 5)
- Organization CRUD endpoints
- User CRUD endpoints
- API key CRUD endpoints
- Multi-tenant query isolation
- **Deliverable**: Organizations and users manageable via API

### Phase 4: Connection Management (Week 6-7)
- Create connection_service with type registry
- Implement SharePoint, LLM, Extraction connection types
- Connection CRUD endpoints
- Test-on-save functionality
- **Deliverable**: Connections manageable and testable via API

### Phase 5: Service Integration (Week 8)
- Modify document_service to use connection_service
- Modify llm_service to use connection_service
- Modify sharepoint_service to use connection_service
- Maintain backward compatibility with ENV
- **Deliverable**: Services use database connections (with ENV fallback)

### Phase 6: Frontend Integration (Week 9-10)
- Login page with JWT handling
- Connection management UI
- Settings management UI
- Token refresh logic
- **Deliverable**: Full UI for authentication and connection management

### Phase 7: Migration & Documentation (Week 11)
- ENV → DB migration command
- Import/export CLI tools
- Documentation updates
- Migration guide
- **Deliverable**: Complete migration path from ENV to DB

### Phase 8: Audit & Security (Week 12)
- Audit log service and endpoints
- Security review (SQL injection, XSS, secret handling)
- Secret redaction in logs
- Rate limiting
- **Deliverable**: Production-ready security posture

## Dependencies to Add

```
# requirements.txt
sqlalchemy[asyncio]==2.0.25
alembic==1.13.1
asyncpg==0.29.0  # PostgreSQL async driver
aiosqlite==0.19.0  # SQLite async driver
pyjwt==2.8.0
bcrypt==4.1.2
python-jose[cryptography]==3.3.0
```

## Environment Variables to Add

```bash
# Database
DATABASE_URL=sqlite+aiosqlite:///./data/curatore.db
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=40

# Authentication
JWT_SECRET_KEY=<generate-with-openssl-rand-hex-32>
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
JWT_REFRESH_TOKEN_EXPIRE_DAYS=30

# Multi-Tenancy
ENABLE_AUTH=true  # Set to false for backward compatibility
DEFAULT_ORG_ID=

# Connection Management
AUTO_TEST_CONNECTIONS=true

# Initial Seeding
ADMIN_EMAIL=admin@example.com
ADMIN_USERNAME=admin
ADMIN_PASSWORD=changeme
DEFAULT_ORG_NAME=Default Organization
```

## Migration Strategy

### Backward Compatibility
- Phase 1-4: ENV-based config continues to work (no breaking changes)
- Phase 5: Add feature flag `ENABLE_AUTH=false` (uses default org/user)
- Phase 6-7: Migrate ENV connections to database on startup
- Phase 8: Optional deprecation of ENV-based connections

### Seed Command
```bash
# Create initial org + admin from ENV
python -m app.commands.seed --create-admin

# Import ENV-based connections to database
python -m app.commands.migrate --import-env-connections
```

## Testing Strategy

### Unit Tests
- Password hashing (bcrypt)
- JWT generation/validation
- API key generation/validation
- Connection type validation
- Configuration precedence logic

### Integration Tests
- User registration → login → access protected endpoint
- Multi-tenant isolation (Org A can't see Org B's data)
- Connection CRUD + test-on-save
- Token refresh flow
- API key authentication

### End-to-End Tests
1. Register organization + admin
2. Login (receive JWT)
3. Create SharePoint connection
4. Test connection (health check)
5. Upload document
6. Process document (using connection)
7. Download result

## Security Considerations

1. **Password Security**: bcrypt with 12 rounds
2. **JWT Security**: Long random secret, short expiration, refresh token rotation
3. **API Key Security**: bcrypt hash, prefix for display, scopes/permissions
4. **SQL Injection**: Always use SQLAlchemy ORM, never raw SQL with user input
5. **Secret Management**: Redact secrets in logs, API responses (writeOnly in schemas)
6. **Multi-Tenant Isolation**: All queries filtered by organization_id
7. **HTTPS**: Enforce in production (verify_ssl=true)
8. **Rate Limiting**: Consider adding to auth endpoints

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Database migration failure | Test in staging, provide rollback scripts, backup before migration |
| Breaking changes for existing users | Feature flags, maintain ENV support during transition, gradual rollout |
| Performance impact from DB queries | Connection pooling, query optimization, caching, monitoring |
| JWT secret compromise | Rotate secrets regularly, use long random secrets, short expiration |
| Secrets in database | Hash with bcrypt, consider secret managers (Vault, AWS Secrets Manager) |
| Async SQLAlchemy complexity | Comprehensive logging, consistent use of context managers |

## Verification Steps

After implementation, verify:

1. **Database Connectivity**
   ```bash
   curl http://localhost:8000/api/v1/system/health/database
   ```

2. **User Registration & Login**
   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/register \
     -H "Content-Type: application/json" \
     -d '{"email":"test@example.com","username":"test","password":"password123"}'

   curl -X POST http://localhost:8000/api/v1/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email_or_username":"test@example.com","password":"password123"}'
   ```

3. **Create Connection**
   ```bash
   curl -X POST http://localhost:8000/api/v1/connections \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d '{"name":"My LLM","connection_type":"llm","config":{...}}'
   ```

4. **Test Connection**
   ```bash
   curl -X POST http://localhost:8000/api/v1/connections/<id>/test \
     -H "Authorization: Bearer <token>"
   ```

5. **Process Document with Connection**
   ```bash
   # Upload document
   curl -X POST http://localhost:8000/api/v1/documents/upload \
     -H "Authorization: Bearer <token>" \
     -F "file=@test.pdf"

   # Process (should use connection from database)
   curl -X POST http://localhost:8000/api/v1/documents/<id>/process \
     -H "Authorization: Bearer <token>"
   ```

## Success Criteria

✅ Users can register, login, and receive JWT tokens
✅ Organizations can be created and managed
✅ Multiple connections per type can be configured
✅ Connections are tested on save and health status tracked
✅ Document processing uses connections from database
✅ ENV-based config still works (backward compatible)
✅ Multi-tenant isolation works (orgs can't see each other's data)
✅ API keys work for headless/backend access
✅ Configuration precedence works correctly (ENV > User > Org > System)
✅ All tests pass (unit, integration, E2E)

---

**Next Steps**: Begin Phase 1 implementation with database models and migrations.
