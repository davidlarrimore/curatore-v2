# SharePoint Integration

Curatore integrates with Microsoft SharePoint to synchronize documents from SharePoint folders. This document covers the sync architecture, configuration, and key concepts.

## Overview

The SharePoint integration allows users to:
- Connect to Microsoft 365 tenants via OAuth (app credentials)
- Configure one-way sync from SharePoint folders
- Automatically extract and index synced documents
- Detect deleted/moved files and update accordingly
- Schedule recurring syncs (hourly, daily, or manual)

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                        SHAREPOINT SYNC ARCHITECTURE                              │
└─────────────────────────────────────────────────────────────────────────────────┘

  Microsoft 365                     Curatore                           Frontend
       │                               │                                  │
       ▼                               ▼                                  ▼
┌─────────────────┐           ┌─────────────────┐              ┌─────────────────┐
│ Graph API Auth  │───────────│   Connection    │              │ /sharepoint-sync│
│ (Client Creds)  │           │ (tenant creds)  │              │                 │
└─────────────────┘           └─────────────────┘              └─────────────────┘
       │                               │                                  │
       ▼                               ▼                                  ▼
┌─────────────────┐           ┌─────────────────┐              ┌─────────────────┐
│ Drive/Folder    │───────────│ SharePointSync  │──────────────│ Config Detail   │
│ Inventory       │           │    Config       │              │ Sync History    │
└─────────────────┘           └─────────────────┘              └─────────────────┘
       │                               │
       ▼                               ▼
┌─────────────────┐           ┌─────────────────┐
│ File Download   │───────────│ Asset + Synced  │──────▶ Extraction Queue
│ (with retry)    │           │   Document      │
└─────────────────┘           └─────────────────┘
```

---

## Database Models

| Model | Purpose |
|-------|---------|
| `Connection` | Microsoft 365 tenant credentials (type: `sharepoint`) |
| `SharePointSyncConfig` | Sync configuration (folder URL, schedule, status) |
| `SharePointSyncedDocument` | Tracks synced files (item_id, etag, last_modified) |
| `Asset` | Created for each synced document |

### SharePointSyncConfig Fields

| Field | Description |
|-------|-------------|
| `name` | User-defined name |
| `folder_url` | SharePoint folder URL |
| `site_id` | Resolved SharePoint site ID |
| `drive_id` | Resolved drive ID |
| `folder_path` | Path within the drive |
| `sync_frequency` | `manual`, `hourly`, or `daily` |
| `status` | `active`, `syncing`, `error`, `archived`, `deleting` |
| `last_synced_at` | Last successful sync timestamp |
| `include_subfolders` | Whether to sync subfolders recursively |

### SharePointSyncedDocument Fields

| Field | Description |
|-------|-------------|
| `sharepoint_item_id` | Microsoft Graph item ID |
| `sharepoint_etag` | ETag for change detection |
| `sharepoint_last_modified` | Last modified in SharePoint |
| `relative_path` | Path relative to sync folder |
| `status` | `synced`, `deleted`, `error` |

---

## Key Service Files

| File | Purpose |
|------|---------|
| `sharepoint_service.py` | Microsoft Graph API client, token management |
| `sharepoint_sync_service.py` | Sync config CRUD, sync execution |

---

## Sync Process

1. **Inventory** - List all files in SharePoint folder (with subfolders if enabled)
2. **Compare** - Check each file against `SharePointSyncedDocument` records
3. **Download new/changed files**:
   - Create `Asset` record
   - Store file in MinIO (`{org_id}/sharepoint/{site}/{path}`)
   - Create `SharePointSyncedDocument` tracking record
   - Queue extraction
4. **Detect deletions** - Files in DB but not in inventory → mark as deleted
5. **Create Run Group** - Track all child extractions
6. **On completion** - Emit `sharepoint_sync.group_completed` event

### Change Detection

Files are re-downloaded when:
- ETag has changed
- Last modified timestamp differs
- File not previously synced

---

## API Endpoints

```
# Connections
GET    /api/v1/connections                          # List connections
POST   /api/v1/connections                          # Create connection
DELETE /api/v1/connections/{id}                     # Delete connection

# Sync Configs
GET    /api/v1/sharepoint/configs                   # List sync configs
POST   /api/v1/sharepoint/configs                   # Create sync config
GET    /api/v1/sharepoint/configs/{id}              # Get config details
PATCH  /api/v1/sharepoint/configs/{id}              # Update config
DELETE /api/v1/sharepoint/configs/{id}              # Delete (async)
POST   /api/v1/sharepoint/configs/{id}/sync         # Trigger manual sync
POST   /api/v1/sharepoint/configs/{id}/archive      # Archive config

# Folder Browser
GET    /api/v1/sharepoint/sites                     # List available sites
GET    /api/v1/sharepoint/sites/{id}/drives         # List drives in site
GET    /api/v1/sharepoint/drives/{id}/children      # Browse folder contents
```

---

## Frontend Pages

| Page | Path | Purpose |
|------|------|---------|
| List | `/sharepoint-sync` | All sync configurations |
| New | `/sharepoint-sync/new` | Create new sync config |
| Detail | `/sharepoint-sync/{configId}` | Config details, sync history, documents |

---

## Connection Setup

### Prerequisites

1. Azure AD App Registration with:
   - `Sites.Read.All` permission (Application type)
   - Client ID and Client Secret

2. Tenant ID from Azure portal

### Creating Connection

1. Navigate to `/connections`
2. Click "Add Connection" → SharePoint
3. Enter:
   - Tenant ID
   - Client ID
   - Client Secret
4. Test connection to verify credentials

---

## Configuration

In `config.yml`:

```yaml
sharepoint:
  enabled: true
  # Optional: default sync settings
  default_sync_frequency: daily
  max_file_size_mb: 100
```

Environment variables (if not using Connection model):
```bash
SHAREPOINT_TENANT_ID=your_tenant_id
SHAREPOINT_CLIENT_ID=your_client_id
SHAREPOINT_CLIENT_SECRET=your_client_secret
```

---

## Storage Paths

```
curatore-uploads/{org_id}/sharepoint/{site_name}/{folder_path}/{filename}
curatore-processed/{org_id}/sharepoint/{site_name}/{folder_path}/{filename}.md
```

---

## Events

| Event | When Emitted |
|-------|--------------|
| `sharepoint_sync.completed` | After sync completes (before extractions) |
| `sharepoint_sync.group_completed` | After all file extractions complete |

---

## Scheduled Sync

Configure scheduled syncs via:
- Set `sync_frequency` on the config (`hourly` or `daily`)
- `sharepoint.trigger_sync` maintenance task runs on schedule
- Skips configs that already have a running sync

---

## Error Handling

### Retry Logic

File downloads include automatic retry for:
- Network errors (connection reset, timeout)
- 401 errors (token refresh)
- 429 rate limiting (respects Retry-After header)

Default: 3 retries with 30-second delay

### Batch Commits

Large syncs commit database changes every 50 files to prevent:
- PostgreSQL checkpoint pressure
- Memory bloat
- Worker stalls

---

## Async Deletion

Deleting a sync config with many files uses async deletion:
1. Config status set to `deleting`
2. Celery task queues cleanup
3. Files removed from MinIO
4. Assets marked as deleted
5. Config record deleted

See [Queue System - Async Deletion Pattern](QUEUE_SYSTEM.md#async-deletion-pattern)

---

## Troubleshooting

### "Access Denied" errors
- Verify Azure AD app has `Sites.Read.All` permission
- Ensure permission is **Application** type (not Delegated)
- Admin consent may be required

### Files not syncing
- Check if file type is supported for extraction
- Verify `include_subfolders` setting
- Check sync config status for errors

### Slow syncs
- Large folders (4000+ files) may take time
- Consider splitting into multiple sync configs
- Check network connectivity to Microsoft Graph API
