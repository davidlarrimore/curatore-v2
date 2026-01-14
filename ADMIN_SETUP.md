# Admin Setup Guide

This guide covers the initial setup and configuration of Curatore v2.

## Default Admin Credentials

Curatore creates a default admin account on first startup:

```
Email:    admin@example.com
Username: admin
Password: changeme
```

**⚠️ SECURITY WARNING**: Change the default password immediately after first login!

---

## Initial Setup

### 1. Start the Application

```bash
# Start all services
./scripts/dev-up.sh

# Or using Make
make up
```

### 2. Create Admin User

The admin user is created automatically when you first start the application. If you need to recreate it or create a custom admin:

```bash
# Create admin user with default credentials (from .env)
docker exec curatore-backend python -m app.commands.seed --create-admin

# Or create with custom credentials
docker exec curatore-backend python -m app.commands.seed \
  --admin-email your-email@example.com \
  --admin-password your-secure-password
```

### 3. Access the Application

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

### 4. Log In

1. Navigate to http://localhost:3000
2. Click "Sign In"
3. Enter the default credentials:
   - Email: `admin@example.com`
   - Password: `changeme`

---

## Post-Setup Security

### Change Default Password

**Immediately after first login:**

1. Click your profile icon in the top-right corner
2. Select "Settings" or "Profile"
3. Navigate to "Security" or "Change Password"
4. Enter your current password (`changeme`)
5. Enter and confirm your new secure password
6. Click "Update Password"

**Strong Password Requirements:**
- Minimum 8 characters
- Mix of uppercase and lowercase letters
- Include numbers and special characters
- Avoid common words or patterns

### Enable Authentication

By default, authentication is **disabled** for backward compatibility. To enable multi-tenant authentication:

1. **Stop the application**:
   ```bash
   ./scripts/dev-down.sh
   ```

2. **Edit your `.env` file**:
   ```bash
   # Change from:
   ENABLE_AUTH=false

   # To:
   ENABLE_AUTH=true
   ```

3. **Restart the application**:
   ```bash
   ./scripts/dev-up.sh
   ```

4. **Verify authentication is enabled**:
   ```bash
   curl http://localhost:8000/api/v1/system/health/comprehensive
   # Should show: "authentication": "enabled"
   ```

### Update JWT Secret

The JWT secret key is used to sign authentication tokens. Change it in production:

1. **Generate a secure secret**:
   ```bash
   openssl rand -hex 32
   ```

2. **Update `.env` file**:
   ```bash
   JWT_SECRET_KEY=your-newly-generated-secret-key-here
   ```

3. **Restart the application** to apply changes

---

## Creating Additional Users

### Via Frontend (Recommended)

1. Log in as admin
2. Navigate to **Users** in the sidebar
3. Click **"Invite User"** or **"Add User"**
4. Fill in the user details:
   - Email address
   - Full name
   - Role: `org_admin`, `member`, or `viewer`
5. Click **"Create"** or **"Send Invitation"**

### Via API

```bash
# Create user via API
curl -X POST http://localhost:8000/api/v1/users/invite \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "full_name": "New User",
    "role": "member"
  }'
```

### Via Command Line

```bash
# Create additional admin user
docker exec curatore-backend python -m app.commands.seed \
  --admin-email admin2@example.com \
  --admin-password SecurePassword123 \
  --admin-username admin2
```

---

## User Roles

Curatore supports three user roles with different permission levels:

| Role | Permissions |
|------|-------------|
| **org_admin** | Full access: manage users, settings, storage, connections, documents |
| **member** | Standard access: create/process documents, view connections |
| **viewer** | Read-only: view documents and processing results |

---

## Creating Organizations

### Default Organization

A default organization is created automatically during initial setup:

- **Name**: Default Organization
- **Slug**: `default`

### Additional Organizations

Currently, additional organizations must be created via the database or API. This feature is under development.

---

## API Keys for Automation

API keys provide headless authentication for scripts and automation:

### Creating API Keys

1. Log in as admin
2. Navigate to **Settings** > **API Keys**
3. Click **"Create API Key"**
4. Enter a descriptive name (e.g., "CI/CD Pipeline")
5. Set an expiration date (optional)
6. Click **"Create"**
7. **Copy the API key immediately** - it won't be shown again!

### Using API Keys

```bash
# Use API key in requests
curl http://localhost:8000/api/v1/documents/upload \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -F "file=@document.pdf"
```

---

## Database Management

### Backup Database

```bash
# SQLite (default)
cp backend/data/curatore.db backend/data/curatore.db.backup

# PostgreSQL
pg_dump curatore > curatore_backup.sql
```

### Reset Database

```bash
# Stop services
./scripts/dev-down.sh

# Remove SQLite database
rm backend/data/curatore.db

# Remove Alembic version (if needed)
rm backend/alembic/versions/*.py

# Restart services (recreates database)
./scripts/dev-up.sh

# Recreate admin user
docker exec curatore-backend python -m app.commands.seed --create-admin
```

---

## Configuration Files

### Environment Variables

Configuration is managed via `.env` file. Key settings:

**Authentication:**
- `ENABLE_AUTH` - Enable/disable authentication
- `JWT_SECRET_KEY` - Secret for JWT tokens
- `ADMIN_EMAIL` - Default admin email
- `ADMIN_PASSWORD` - Default admin password

**LLM Configuration:**
- `OPENAI_API_KEY` - API key for LLM provider
- `OPENAI_MODEL` - Model name (e.g., `gpt-4o-mini`)
- `OPENAI_BASE_URL` - API endpoint

**Storage:**
- `FILE_DEDUPLICATION_ENABLED` - Enable file deduplication
- `FILE_RETENTION_UPLOADED_DAYS` - Retention for uploaded files
- `FILE_CLEANUP_ENABLED` - Enable automatic cleanup

See `.env.example` for complete list of configuration options.

---

## Troubleshooting

### Cannot Log In

**Problem**: Login fails with default credentials

**Solutions**:
1. Verify services are running: `docker ps`
2. Check backend logs: `./scripts/dev-logs.sh backend`
3. Recreate admin user:
   ```bash
   docker exec curatore-backend python -m app.commands.seed --create-admin
   ```

### Authentication Disabled

**Problem**: Cannot access protected routes

**Solution**: Enable authentication in `.env`:
```bash
ENABLE_AUTH=true
```

### Forgot Password

**Problem**: Lost admin password

**Solutions**:

1. **Reset via database** (SQLite):
   ```bash
   docker exec -it curatore-backend python
   >>> from app.database import get_db
   >>> from app.models import User
   >>> from app.utils.security import get_password_hash
   >>> # Reset password (requires manual database update)
   ```

2. **Recreate admin user**:
   ```bash
   # Remove existing admin and recreate
   docker exec curatore-backend python -m app.commands.seed \
     --create-admin --force
   ```

### Check System Health

```bash
# Comprehensive health check
curl http://localhost:8000/api/v1/system/health/comprehensive | jq '.'

# Individual service checks
curl http://localhost:8000/api/v1/system/health/backend
curl http://localhost:8000/api/v1/system/health/redis
curl http://localhost:8000/api/v1/system/health/celery
```

---

## Production Deployment

### Security Checklist

Before deploying to production:

- [ ] Change default admin password
- [ ] Generate and set secure `JWT_SECRET_KEY`
- [ ] Enable authentication (`ENABLE_AUTH=true`)
- [ ] Configure HTTPS/TLS certificates
- [ ] Set strong `ADMIN_PASSWORD` in `.env`
- [ ] Configure email backend for notifications
- [ ] Set appropriate file retention policies
- [ ] Review CORS origins settings
- [ ] Disable debug mode (`DEBUG=false`)
- [ ] Use PostgreSQL instead of SQLite for database
- [ ] Set up regular database backups
- [ ] Configure monitoring and logging
- [ ] Review and restrict API access

### Environment Variables to Update

```bash
# Security
JWT_SECRET_KEY=<generated-with-openssl-rand-hex-32>
ADMIN_PASSWORD=<strong-unique-password>
ENABLE_AUTH=true
DEBUG=false

# Database (Production)
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/curatore

# CORS
CORS_ORIGINS=["https://your-domain.com"]

# Frontend URL
FRONTEND_BASE_URL=https://your-domain.com
NEXT_PUBLIC_API_URL=https://api.your-domain.com
```

See [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md) for complete production deployment instructions.

---

## Support

For issues, questions, or contributions:

- **Documentation**: See project README.md and other guides
- **API Documentation**: http://localhost:8000/docs
- **Health Checks**: http://localhost:8000/api/v1/system/health/comprehensive
- **Logs**: `./scripts/dev-logs.sh [service]`

---

## Quick Reference

```bash
# Start services
./scripts/dev-up.sh

# Stop services
./scripts/dev-down.sh

# Create admin user
docker exec curatore-backend python -m app.commands.seed --create-admin

# View logs
./scripts/dev-logs.sh

# Check health
curl http://localhost:8000/api/v1/system/health/comprehensive

# Access application
open http://localhost:3000
```
