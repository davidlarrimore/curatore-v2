# Curatore v2 - Deployment Guide

**Version**: 2.0.0
**Last Updated**: 2026-01-13

---

## Table of Contents

1. [Overview](#overview)
2. [System Requirements](#system-requirements)
3. [Deployment Options](#deployment-options)
4. [Docker Deployment](#docker-deployment)
5. [Environment Configuration](#environment-configuration)
6. [Database Setup](#database-setup)
7. [Service Configuration](#service-configuration)
8. [SSL/TLS Configuration](#ssltls-configuration)
9. [Production Checklist](#production-checklist)
10. [Monitoring and Logging](#monitoring-and-logging)
11. [Backup and Recovery](#backup-and-recovery)
12. [Scaling and Performance](#scaling-and-performance)
13. [Security Hardening](#security-hardening)
14. [Troubleshooting](#troubleshooting)
15. [Upgrade Procedures](#upgrade-procedures)

---

## Overview

This guide covers deploying Curatore v2 in production environments. Curatore is a containerized application using Docker Compose, designed for scalability and maintainability.

### Architecture Components

- **Frontend**: Next.js 15.5 (React 19, Tailwind CSS)
- **Backend API**: FastAPI (Python 3.12+)
- **Worker**: Celery with async task processing
- **Queue**: Redis for Celery broker and result backend
- **Database**: PostgreSQL (production) or SQLite (development)
- **Extraction Service**: Standalone document conversion microservice
- **Docling** (optional): Advanced document extraction

### Deployment Modes

1. **Single Server**: All components on one server (small-medium workloads)
2. **Multi-Server**: Distributed deployment (high availability)
3. **Kubernetes**: Container orchestration (enterprise scale)

This guide focuses on **Docker Compose single-server deployment** suitable for most use cases.

---

## System Requirements

### Hardware Requirements

#### Minimum (Development/Testing)
- **CPU**: 2 cores
- **RAM**: 4 GB
- **Storage**: 20 GB SSD
- **Network**: 10 Mbps

#### Recommended (Small Production)
- **CPU**: 4 cores
- **RAM**: 8 GB
- **Storage**: 100 GB SSD
- **Network**: 100 Mbps

#### Production (Medium-Large)
- **CPU**: 8+ cores
- **RAM**: 16+ GB
- **Storage**: 500 GB SSD (NVMe preferred)
- **Network**: 1 Gbps

### Software Requirements

#### Operating System
- **Linux**: Ubuntu 22.04 LTS, Debian 11+, RHEL 8+, Amazon Linux 2
- **macOS**: macOS 12+ (development only)
- **Windows**: Windows Server 2019+ with WSL2 (not recommended for production)

#### Required Software
- **Docker**: 24.0+
- **Docker Compose**: 2.20+
- **Git**: 2.30+
- **curl**: For health checks and testing

#### Optional Software
- **nginx**: Reverse proxy with SSL termination
- **PostgreSQL Client**: For database management
- **Redis CLI**: For queue inspection

### Network Requirements

#### Inbound Ports
- **80/443**: HTTP/HTTPS (nginx)
- **8000**: Backend API (if no reverse proxy)
- **3000**: Frontend (if no reverse proxy)
- **22**: SSH (for administration)

#### Outbound Connectivity
- **OpenAI API**: port 443 (if using LLM features)
- **Microsoft Graph**: port 443 (if using SharePoint integration)
- **Package Registries**: Docker Hub, npm, PyPI (for updates)

---

## Deployment Options

### Option 1: Docker Compose (Recommended)

**Best For**: Single server deployments, small to medium scale

**Pros**:
- Simple setup and management
- All services defined in one file
- Easy to version control
- Minimal operational overhead

**Cons**:
- Single point of failure
- Limited horizontal scaling

### Option 2: Kubernetes

**Best For**: Enterprise deployments, high availability requirements

**Pros**:
- Horizontal scaling
- High availability
- Rolling updates
- Self-healing

**Cons**:
- Complex setup and management
- Requires Kubernetes expertise
- Higher resource overhead

### Option 3: Cloud-Native (AWS/Azure/GCP)

**Best For**: Cloud-first organizations, managed services

**Pros**:
- Managed databases and Redis
- Auto-scaling
- Built-in monitoring
- Geographic distribution

**Cons**:
- Higher costs
- Vendor lock-in
- Learning curve for cloud services

This guide focuses on **Option 1: Docker Compose** deployment.

---

## Docker Deployment

### Prerequisites

1. **Server Setup**
   ```bash
   # Update system packages
   sudo apt update && sudo apt upgrade -y

   # Install Docker
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh

   # Add current user to docker group
   sudo usermod -aG docker $USER

   # Install Docker Compose
   sudo curl -L "https://github.com/docker/compose/releases/download/v2.23.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
   sudo chmod +x /usr/local/bin/docker-compose

   # Verify installations
   docker --version
   docker-compose --version
   ```

2. **Clone Repository**
   ```bash
   # Create application directory
   sudo mkdir -p /opt/curatore
   sudo chown $USER:$USER /opt/curatore
   cd /opt/curatore

   # Clone repository
   git clone https://github.com/yourorg/curatore-v2.git .

   # Checkout specific version (recommended for production)
   git checkout v2.0.0
   ```

3. **Configure Environment**
   ```bash
   # Copy example environment file
   cp .env.example .env

   # Edit configuration (see Environment Configuration section)
   nano .env
   ```

### Directory Structure

```
/opt/curatore/
├── backend/              # Backend API code
├── frontend/             # Frontend Next.js code
├── extraction-service/   # Extraction service code
├── docker-compose.yml    # Service definitions
├── .env                  # Environment configuration
├── scripts/              # Utility scripts
│   ├── dev-up.sh
│   ├── dev-down.sh
│   └── ...
└── data/                 # Persistent data (created on first run)
    ├── files/            # Document storage
    │   ├── uploaded_files/
    │   ├── processed_files/
    │   ├── batch_files/
    │   └── dedupe/
    ├── db/               # Database files (if using SQLite)
    └── logs/             # Application logs
```

### Initial Deployment

1. **Start Services**
   ```bash
   # Start all services
   docker-compose up -d

   # View logs
   docker-compose logs -f

   # Check service status
   docker-compose ps
   ```

2. **Initialize Database**
   ```bash
   # Run database migrations
   docker-compose exec backend alembic upgrade head

   # Create admin user and default organization
   docker-compose exec backend python -m app.commands.seed --create-admin

   # Note the organization ID and admin credentials
   ```

3. **Verify Deployment**
   ```bash
   # Check backend health
   curl http://localhost:8000/api/v1/health

   # Check comprehensive health
   curl http://localhost:8000/api/v1/system/health/comprehensive | jq '.'

   # Access frontend
   curl http://localhost:3000
   ```

4. **Test Document Processing**
   ```bash
   # Upload a test document
   curl -X POST http://localhost:8000/api/v1/documents/upload \
     -H "Authorization: ApiKey cur_your_api_key" \
     -F "file=@test.pdf"
   ```

### Service Management

```bash
# Start all services
docker-compose up -d

# Stop all services
docker-compose down

# Restart specific service
docker-compose restart backend

# View logs for specific service
docker-compose logs -f backend

# Scale workers (run 4 worker containers)
docker-compose up -d --scale worker=4

# Pull latest images
docker-compose pull

# Rebuild images
docker-compose build

# Remove volumes (WARNING: deletes data)
docker-compose down -v
```

### Update Deployment

```bash
# Pull latest code
git pull origin main

# Rebuild and restart services
docker-compose down
docker-compose build
docker-compose up -d

# Run database migrations (if any)
docker-compose exec backend alembic upgrade head
```

---

## Environment Configuration

### Core Configuration

Copy `.env.example` to `.env` and configure:

#### Application Settings

```bash
# Application Mode
DEBUG=false                          # Production: false, Development: true
ENVIRONMENT=production               # production, staging, development

# API Configuration
API_TITLE="Curatore v2"
API_VERSION="2.0.0"

# CORS Configuration (adjust for your domain)
CORS_ORIGINS=["https://curatore.yourcompany.com"]
CORS_ORIGIN_REGEX=""
```

#### Authentication

```bash
# Enable authentication (required for multi-tenant mode)
ENABLE_AUTH=true

# JWT Configuration
JWT_SECRET_KEY="your-secret-key-change-in-production"  # CHANGE THIS!
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60
JWT_REFRESH_TOKEN_EXPIRE_DAYS=30

# Password Security
BCRYPT_ROUNDS=12                     # Higher = more secure but slower

# API Key Configuration
API_KEY_PREFIX="cur_"
```

**Security Note**: Generate a strong JWT secret key:
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

#### Database Configuration

```bash
# PostgreSQL (Production - Recommended)
DATABASE_URL="postgresql+asyncpg://curatore:password@postgres:5432/curatore"

# Connection Pool Settings
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=40
DB_POOL_RECYCLE=3600

# SQLite (Development Only)
# DATABASE_URL="sqlite+aiosqlite:///./data/curatore.db"
```

#### Redis Configuration

```bash
# Redis Connection
CELERY_BROKER_URL="redis://redis:6379/0"
CELERY_RESULT_BACKEND="redis://redis:6379/1"
CELERY_DEFAULT_QUEUE="processing"
```

#### File Storage

```bash
# Storage Paths (Docker volumes)
FILES_ROOT="/app/files"
UPLOAD_DIR="/app/files/uploaded_files"
PROCESSED_DIR="/app/files/processed_files"
BATCH_DIR="/app/files/batch_files"

# Storage Retention (days)
UPLOAD_FILE_RETENTION_DAYS=30
PROCESSED_FILE_RETENTION_DAYS=90
BATCH_FILE_RETENTION_DAYS=60
TEMP_FILE_RETENTION_DAYS=1

# Deduplication
ENABLE_DEDUPLICATION=true
HASH_ALGORITHM="sha256"
```

#### Extraction Configuration

```bash
# Extraction Service
EXTRACTION_SERVICE_URL="http://extraction:8010"

# Docling (optional)
ENABLE_DOCLING_SERVICE=false
DOCLING_SERVICE_URL="http://docling:5001"
```

#### LLM Configuration

```bash
# OpenAI API (or compatible)
OPENAI_API_KEY="sk-..."             # Your API key
OPENAI_MODEL="gpt-4o-mini"          # Model to use
OPENAI_BASE_URL="https://api.openai.com/v1"  # API endpoint
OPENAI_TIMEOUT=30                    # Request timeout (seconds)

# Quality Thresholds (0-100 or 1-10 depending on metric)
DEFAULT_CONVERSION_THRESHOLD=70
DEFAULT_CLARITY_THRESHOLD=7
DEFAULT_COMPLETENESS_THRESHOLD=7
DEFAULT_RELEVANCE_THRESHOLD=7
DEFAULT_MARKDOWN_THRESHOLD=7
```

#### Email Configuration (Optional)

```bash
# Email Backend: console, smtp, sendgrid, ses
EMAIL_BACKEND="smtp"

# Email Settings
EMAIL_FROM_ADDRESS="noreply@curatore.yourcompany.com"
EMAIL_FROM_NAME="Curatore"
FRONTEND_BASE_URL="https://curatore.yourcompany.com"

# SMTP Settings (if using smtp backend)
SMTP_HOST="smtp.gmail.com"
SMTP_PORT=587
SMTP_USERNAME="your-email@gmail.com"
SMTP_PASSWORD="your-app-password"
SMTP_TLS=true

# SendGrid (if using sendgrid backend)
SENDGRID_API_KEY="SG..."

# AWS SES (if using ses backend)
AWS_REGION="us-east-1"
AWS_ACCESS_KEY_ID="AKIA..."
AWS_SECRET_ACCESS_KEY="..."

# Email Verification
EMAIL_VERIFICATION_TOKEN_EXPIRE_HOURS=24
EMAIL_VERIFICATION_GRACE_PERIOD_DAYS=7

# Password Reset
PASSWORD_RESET_TOKEN_EXPIRE_HOURS=1
```

#### SharePoint Configuration (Optional)

```bash
# Microsoft Graph API
MS_TENANT_ID="your-tenant-id"
MS_CLIENT_ID="your-client-id"
MS_CLIENT_SECRET="your-client-secret"
MS_GRAPH_SCOPE="https://graph.microsoft.com/.default"
MS_GRAPH_BASE_URL="https://graph.microsoft.com/v1.0"
```

#### Initial Seeding (First-Time Setup)

```bash
# Default Organization
DEFAULT_ORG_NAME="Your Company"
DEFAULT_ORG_SLUG="yourcompany"

# Admin User
ADMIN_EMAIL="admin@yourcompany.com"
ADMIN_USERNAME="admin"
ADMIN_PASSWORD="change-me-on-first-login"
ADMIN_FULL_NAME="System Administrator"
```

### Docker Compose Configuration

The `docker-compose.yml` file defines all services. Key configuration options:

#### Resource Limits

```yaml
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '1'
          memory: 1G
```

#### Port Mappings

```yaml
ports:
  - "8000:8000"  # Backend API
  - "3000:3000"  # Frontend
  - "6379:6379"  # Redis (for debugging only)
```

#### Volume Mounts

```yaml
volumes:
  - ./data/files:/app/files        # Document storage
  - ./data/db:/app/data            # Database (SQLite only)
  - ./data/logs:/app/logs          # Application logs
```

---

## Database Setup

### PostgreSQL (Production)

#### Using Docker Compose

Add to `docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: curatore
      POSTGRES_USER: curatore
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U curatore"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

Update `.env`:
```bash
DATABASE_URL="postgresql+asyncpg://curatore:${POSTGRES_PASSWORD}@postgres:5432/curatore"
POSTGRES_PASSWORD="generate-strong-password-here"
```

#### Using External PostgreSQL

If using managed PostgreSQL (AWS RDS, Azure Database, etc.):

```bash
DATABASE_URL="postgresql+asyncpg://user:password@db.example.com:5432/curatore"
```

#### Initial Database Setup

```bash
# Run migrations
docker-compose exec backend alembic upgrade head

# Create admin user
docker-compose exec backend python -m app.commands.seed --create-admin

# Verify database
docker-compose exec backend python -c "from app.services.database_service import database_service; import asyncio; print(asyncio.run(database_service.health_check()))"
```

#### Database Maintenance

```bash
# Backup database
docker-compose exec postgres pg_dump -U curatore curatore > backup.sql

# Restore database
docker-compose exec -T postgres psql -U curatore curatore < backup.sql

# Vacuum database (optimize performance)
docker-compose exec postgres psql -U curatore -c "VACUUM ANALYZE;"
```

### SQLite (Development Only)

SQLite is suitable for development and testing, but **not recommended for production**.

```bash
DATABASE_URL="sqlite+aiosqlite:///./data/curatore.db"
```

**Limitations**:
- No concurrent writes
- Limited scalability
- No replication
- Single point of failure

---

## Service Configuration

### Backend API

#### Health Checks

```bash
# Basic health
curl http://localhost:8000/api/v1/health

# Comprehensive health
curl http://localhost:8000/api/v1/system/health/comprehensive | jq '.'
```

#### Logging

Configure logging in backend:

```bash
# Log level
LOG_LEVEL="INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL

# Log format
LOG_FORMAT="json"  # json, text

# Log location
LOG_DIR="/app/logs"
```

Logs are available at:
- **Container**: `/app/logs/api.log`
- **Host**: `./data/logs/api.log`

#### Performance Tuning

```bash
# Uvicorn workers (backend API)
UVICORN_WORKERS=4  # Recommended: 2-4 per CPU core

# Timeout settings
UVICORN_TIMEOUT=60  # Request timeout (seconds)
UVICORN_KEEPALIVE=5  # Keep-alive timeout (seconds)
```

### Celery Workers

#### Scaling Workers

```bash
# Run 4 worker containers
docker-compose up -d --scale worker=4

# Check worker status
docker-compose exec worker celery -A app.celery_app inspect active
```

#### Worker Configuration

```bash
# Concurrency (tasks per worker)
CELERY_WORKER_CONCURRENCY=4  # Recommended: CPU cores

# Task timeout
CELERY_TASK_TIME_LIMIT=600  # 10 minutes
CELERY_TASK_SOFT_TIME_LIMIT=540  # 9 minutes (soft limit)

# Task retry
CELERY_TASK_MAX_RETRIES=3
CELERY_TASK_RETRY_DELAY=60  # seconds
```

#### Monitoring Workers

```bash
# Active tasks
docker-compose exec worker celery -A app.celery_app inspect active

# Registered tasks
docker-compose exec worker celery -A app.celery_app inspect registered

# Worker stats
docker-compose exec worker celery -A app.celery_app inspect stats
```

### Frontend

#### Build Configuration

For production, build optimized frontend:

```bash
# Build frontend
docker-compose exec frontend npm run build

# Start production server
docker-compose exec frontend npm start
```

#### Environment Variables

Frontend uses `NEXT_PUBLIC_*` variables:

```bash
NEXT_PUBLIC_API_URL="https://api.curatore.yourcompany.com"
```

### Redis

#### Configuration

Redis requires minimal configuration for Curatore:

```yaml
redis:
  image: redis:7-alpine
  command: redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru
```

#### Monitoring

```bash
# Connect to Redis CLI
docker-compose exec redis redis-cli

# Check memory usage
docker-compose exec redis redis-cli INFO memory

# Check key count
docker-compose exec redis redis-cli DBSIZE

# Monitor commands
docker-compose exec redis redis-cli MONITOR
```

---

## SSL/TLS Configuration

### Using nginx Reverse Proxy

#### Install nginx

```bash
sudo apt install nginx
```

#### Configure nginx

Create `/etc/nginx/sites-available/curatore`:

```nginx
# Redirect HTTP to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name curatore.yourcompany.com;

    return 301 https://$server_name$request_uri;
}

# HTTPS Configuration
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name curatore.yourcompany.com;

    # SSL Certificate (Let's Encrypt)
    ssl_certificate /etc/letsencrypt/live/curatore.yourcompany.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/curatore.yourcompany.com/privkey.pem;
    ssl_trusted_certificate /etc/letsencrypt/live/curatore.yourcompany.com/chain.pem;

    # SSL Configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    ssl_stapling on;
    ssl_stapling_verify on;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Frontend (Next.js)
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }

    # Backend API
    location /api {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts for long-running requests
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;

        # File upload limits
        client_max_body_size 50M;
    }

    # Backend docs
    location ~ ^/(docs|redoc|openapi.json) {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### Enable Site

```bash
# Create symlink
sudo ln -s /etc/nginx/sites-available/curatore /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

### SSL Certificates with Let's Encrypt

```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx

# Obtain certificate
sudo certbot --nginx -d curatore.yourcompany.com

# Auto-renewal (already configured by certbot)
sudo systemctl status certbot.timer
```

### Update Environment

Update frontend environment to use HTTPS:

```bash
NEXT_PUBLIC_API_URL="https://curatore.yourcompany.com/api/v1"
```

---

## Production Checklist

Before deploying to production, verify:

### Security

- [ ] Change default passwords (admin, database, JWT secret)
- [ ] Generate strong JWT secret key
- [ ] Configure SSL/TLS certificates
- [ ] Enable HTTPS redirect
- [ ] Set secure CORS origins
- [ ] Configure firewall rules
- [ ] Disable debug mode (`DEBUG=false`)
- [ ] Review file permissions
- [ ] Enable API rate limiting (if available)
- [ ] Secure API keys and secrets

### Configuration

- [ ] Set `ENVIRONMENT=production`
- [ ] Configure production database (PostgreSQL)
- [ ] Set appropriate resource limits
- [ ] Configure email service
- [ ] Set up backup strategy
- [ ] Configure log retention
- [ ] Set storage retention policies
- [ ] Configure monitoring and alerts

### Database

- [ ] Run database migrations
- [ ] Create admin user
- [ ] Test database connection
- [ ] Configure backup automation
- [ ] Set up connection pooling
- [ ] Test database failover (if applicable)

### Services

- [ ] Verify all services start correctly
- [ ] Test health endpoints
- [ ] Verify document processing
- [ ] Test email delivery
- [ ] Test SharePoint integration (if used)
- [ ] Verify LLM integration
- [ ] Test API authentication
- [ ] Verify file uploads/downloads

### Performance

- [ ] Set appropriate worker concurrency
- [ ] Configure resource limits
- [ ] Test with expected load
- [ ] Verify queue processing
- [ ] Monitor memory usage
- [ ] Monitor disk usage

### Monitoring

- [ ] Set up health check monitoring
- [ ] Configure log aggregation
- [ ] Set up error alerts
- [ ] Monitor disk space
- [ ] Monitor memory usage
- [ ] Monitor API response times

### Documentation

- [ ] Document deployment procedure
- [ ] Document backup/restore procedure
- [ ] Document rollback procedure
- [ ] Document troubleshooting steps
- [ ] Create runbooks for common operations

---

## Monitoring and Logging

### Application Logs

#### Backend Logs

```bash
# View backend logs
docker-compose logs -f backend

# View logs in files
tail -f ./data/logs/api.log

# Search logs
grep "ERROR" ./data/logs/api.log
```

#### Worker Logs

```bash
# View worker logs
docker-compose logs -f worker

# View specific worker
docker-compose logs -f worker_1
```

#### Frontend Logs

```bash
# View frontend logs
docker-compose logs -f frontend
```

### Health Monitoring

#### Comprehensive Health Check

```bash
curl https://curatore.yourcompany.com/api/v1/system/health/comprehensive
```

Response includes:
- API status
- Database connectivity
- Redis connectivity
- Celery workers
- Extraction service
- LLM service
- SharePoint connectivity (if configured)

#### Individual Component Checks

```bash
# Backend
curl https://curatore.yourcompany.com/api/v1/health

# Database
curl https://curatore.yourcompany.com/api/v1/system/health/backend

# Redis
curl https://curatore.yourcompany.com/api/v1/system/health/redis

# Workers
curl https://curatore.yourcompany.com/api/v1/system/health/celery
```

### Monitoring Tools

#### Prometheus + Grafana (Recommended)

Add to `docker-compose.yml`:

```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:latest
    volumes:
      - grafana_data:/var/lib/grafana
    ports:
      - "3001:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin

volumes:
  prometheus_data:
  grafana_data:
```

#### Log Aggregation (ELK Stack)

For centralized logging, consider:
- **Elasticsearch**: Log storage
- **Logstash**: Log processing
- **Kibana**: Log visualization

#### Uptime Monitoring

Use external monitoring services:
- **UptimeRobot**: Free tier available
- **Pingdom**: Comprehensive monitoring
- **StatusCake**: Uptime and performance

Configure health check URL:
```
https://curatore.yourcompany.com/api/v1/health
```

---

## Backup and Recovery

### Database Backup

#### Automated Backup Script

Create `/opt/curatore/scripts/backup.sh`:

```bash
#!/bin/bash
BACKUP_DIR="/opt/curatore/backups"
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p $BACKUP_DIR

# Backup PostgreSQL
docker-compose exec -T postgres pg_dump -U curatore curatore | gzip > $BACKUP_DIR/db_${DATE}.sql.gz

# Backup files
tar -czf $BACKUP_DIR/files_${DATE}.tar.gz ./data/files

# Keep only last 30 days of backups
find $BACKUP_DIR -name "*.gz" -mtime +30 -delete

echo "Backup completed: $DATE"
```

#### Schedule with Cron

```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * /opt/curatore/scripts/backup.sh >> /opt/curatore/logs/backup.log 2>&1
```

### Restore from Backup

```bash
# Stop services
docker-compose down

# Restore database
gunzip < backup.sql.gz | docker-compose exec -T postgres psql -U curatore curatore

# Restore files
tar -xzf files_backup.tar.gz -C ./data/

# Start services
docker-compose up -d
```

### Disaster Recovery

#### Backup Strategy

1. **Daily automated backups** of database and files
2. **Offsite backup storage** (S3, Azure Blob, etc.)
3. **Test restores monthly** to verify backup integrity
4. **Document restore procedures** with screenshots
5. **Keep 30 days** of backups

#### Recovery Time Objective (RTO)

Target: **4 hours** from failure detection to service restoration

#### Recovery Point Objective (RPO)

Target: **24 hours** of data loss maximum (daily backups)

---

## Scaling and Performance

### Horizontal Scaling

#### Scale Workers

```bash
# Run 8 worker containers
docker-compose up -d --scale worker=8
```

#### Load Balancing

For multiple backend instances, use nginx load balancing:

```nginx
upstream backend {
    least_conn;
    server backend1:8000;
    server backend2:8000;
    server backend3:8000;
}

location /api {
    proxy_pass http://backend;
    # ... other settings
}
```

### Vertical Scaling

#### Increase Resources

Update `docker-compose.yml`:

```yaml
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 8G
```

### Performance Optimization

#### Database Optimization

```sql
-- Add indexes for common queries
CREATE INDEX idx_documents_org ON documents(organization_id);
CREATE INDEX idx_jobs_status ON jobs(status);
CREATE INDEX idx_users_email ON users(email);
```

#### Redis Optimization

```bash
# Increase max memory
docker-compose exec redis redis-cli CONFIG SET maxmemory 2gb
```

#### Worker Optimization

```bash
# Increase concurrency per worker
CELERY_WORKER_CONCURRENCY=8

# Use prefork pool for CPU-bound tasks
CELERY_WORKER_POOL=prefork
```

---

## Security Hardening

### Application Security

1. **Strong Passwords**
   - Minimum 12 characters
   - Require special characters
   - Enforce password rotation

2. **JWT Security**
   - Use strong secret key (32+ bytes)
   - Short access token expiry (60 minutes)
   - Rotate secrets regularly

3. **API Security**
   - Enable rate limiting
   - Validate all inputs
   - Sanitize outputs
   - Use HTTPS only

4. **File Upload Security**
   - Validate file types
   - Scan for malware
   - Limit file sizes
   - Isolate uploaded files

### System Security

1. **Firewall Configuration**
   ```bash
   # Allow SSH
   sudo ufw allow 22/tcp

   # Allow HTTP/HTTPS
   sudo ufw allow 80/tcp
   sudo ufw allow 443/tcp

   # Enable firewall
   sudo ufw enable
   ```

2. **SSH Hardening**
   ```bash
   # Disable root login
   sudo nano /etc/ssh/sshd_config
   # Set: PermitRootLogin no
   # Set: PasswordAuthentication no (use keys only)

   # Restart SSH
   sudo systemctl restart sshd
   ```

3. **Automatic Updates**
   ```bash
   # Install unattended upgrades
   sudo apt install unattended-upgrades

   # Enable automatic security updates
   sudo dpkg-reconfigure -plow unattended-upgrades
   ```

4. **Intrusion Detection**
   ```bash
   # Install fail2ban
   sudo apt install fail2ban

   # Enable and start
   sudo systemctl enable fail2ban
   sudo systemctl start fail2ban
   ```

---

## Troubleshooting

### Common Issues

#### Services Won't Start

**Symptoms**: `docker-compose up` fails

**Solutions**:
```bash
# Check logs
docker-compose logs

# Check port conflicts
sudo netstat -tulpn | grep :8000

# Check disk space
df -h

# Check Docker status
sudo systemctl status docker

# Restart Docker
sudo systemctl restart docker
```

#### Database Connection Fails

**Symptoms**: Backend can't connect to database

**Solutions**:
```bash
# Verify database is running
docker-compose ps postgres

# Check database logs
docker-compose logs postgres

# Test connection
docker-compose exec backend python -c "from app.services.database_service import database_service; import asyncio; print(asyncio.run(database_service.health_check()))"

# Verify DATABASE_URL in .env
grep DATABASE_URL .env
```

#### Worker Not Processing Jobs

**Symptoms**: Jobs stuck in PENDING status

**Solutions**:
```bash
# Check worker status
docker-compose ps worker

# Check worker logs
docker-compose logs worker

# Check Redis connection
docker-compose exec redis redis-cli PING

# Restart workers
docker-compose restart worker
```

#### High Memory Usage

**Symptoms**: System running out of memory

**Solutions**:
```bash
# Check memory usage
free -h
docker stats

# Reduce worker concurrency
# Edit .env: CELERY_WORKER_CONCURRENCY=2

# Restart with lower limits
docker-compose down
docker-compose up -d
```

#### Slow Performance

**Symptoms**: Requests take longer than expected

**Solutions**:
```bash
# Check resource usage
docker stats

# Check disk I/O
iostat -x 1

# Check database performance
docker-compose exec postgres pg_stat_statements

# Scale workers
docker-compose up -d --scale worker=4

# Check LLM API response times
curl -w "@curl-format.txt" https://api.openai.com/v1/models
```

---

## Upgrade Procedures

### Minor Version Upgrade

For patch releases (e.g., 2.0.0 → 2.0.1):

```bash
# Backup database and files
./scripts/backup.sh

# Pull latest code
git pull origin main
git checkout v2.0.1

# Rebuild images
docker-compose build

# Restart services
docker-compose down
docker-compose up -d

# Verify health
curl http://localhost:8000/api/v1/system/health/comprehensive
```

### Major Version Upgrade

For major releases (e.g., 2.0.0 → 3.0.0):

1. **Review Release Notes**: Check for breaking changes
2. **Backup Everything**: Database, files, configuration
3. **Test in Staging**: Deploy to staging environment first
4. **Run Migrations**: Apply database migrations
5. **Update Configuration**: Modify .env as needed
6. **Deploy**: Follow deployment procedure
7. **Verify**: Test all functionality
8. **Monitor**: Watch logs for errors

### Rollback Procedure

If upgrade fails:

```bash
# Stop services
docker-compose down

# Restore database
gunzip < backup.sql.gz | docker-compose exec -T postgres psql -U curatore curatore

# Restore files
tar -xzf files_backup.tar.gz -C ./data/

# Checkout previous version
git checkout v2.0.0

# Rebuild and start
docker-compose build
docker-compose up -d

# Verify
curl http://localhost:8000/api/v1/health
```

---

## Support

### Getting Help

- **Documentation**: [USER_GUIDE.md](USER_GUIDE.md), [API_DOCUMENTATION.md](API_DOCUMENTATION.md)
- **GitHub Issues**: Report bugs and feature requests
- **Email Support**: support@curatore.io (enterprise customers)

### Reporting Issues

When reporting issues, include:
- Curatore version
- Operating system and version
- Docker and Docker Compose versions
- Error messages and logs
- Steps to reproduce
- Expected vs actual behavior

---

**Last Updated**: 2026-01-13
**Version**: 2.0.0
**Maintained by**: Curatore Development Team
