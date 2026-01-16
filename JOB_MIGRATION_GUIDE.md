# Job Management System Migration Guide

## Overview

Curatore v2 has transitioned from a document-centric 3-stage processing workflow to a comprehensive job management system. This guide will help you understand the changes and migrate your workflows.

---

## What's Changing?

### Old System: 3-Stage Process Page (`/process`)

The previous workflow required navigating through three sequential stages:

1. **Upload & Select**: Choose files to process
2. **Review**: View processing results as they complete
3. **Download**: Export processed documents

**Limitations:**
- Only one batch could be processed at a time
- No tracking of historical processing runs
- Manual monitoring required during processing
- No organization-wide visibility for administrators
- Limited concurrency control

### New System: Job Management (`/jobs`)

The new system provides comprehensive batch job tracking:

- **Batch Jobs**: Group multiple documents into a named, tracked job
- **Concurrent Processing**: Run multiple jobs simultaneously (with org limits)
- **Historical Tracking**: Complete job history with searchable records
- **Real-time Updates**: Live progress updates and logs
- **Admin Visibility**: Organization-wide metrics and statistics
- **Retention Policies**: Automatic cleanup of old jobs

---

## Key Benefits

### For End Users

1. **Multiple Active Jobs**: Process several batches simultaneously
2. **Job History**: Access past processing runs and results
3. **Better Tracking**: Named jobs with descriptions for easy identification
4. **Resume Capability**: Jobs persist across browser sessions
5. **Clearer Status**: Document-level status within each job

### For Administrators

1. **Concurrency Control**: Per-organization limits prevent resource exhaustion
2. **Usage Metrics**: Track processing volume and performance
3. **Cost Management**: Monitor resource usage across the organization
4. **Retention Policies**: Configurable auto-cleanup (7/30/90/indefinite days)
5. **Capacity Planning**: Real-time visibility into active jobs vs. limits

---

## Migration Paths

### Option 1: Use the New Jobs Page (Recommended)

**For Interactive Users:**

1. Navigate to **Jobs** in the left sidebar (or press `Cmd/Ctrl + J`)
2. Click **Create New Job** button
3. Follow the 3-step wizard:
   - **Select**: Upload files or choose from batch directory
   - **Configure**: Set processing options and quality thresholds
   - **Review**: Name your job and start processing
4. Monitor progress in real-time on the job detail page
5. Download results when complete

**Keyboard Shortcuts:**
- `Cmd/Ctrl + J`: Navigate to Jobs page
- `Cmd/Ctrl + P`: Navigate to Process page (deprecated)

### Option 2: Continue Using Process Page (Temporary)

The old `/process` page remains available during the transition period but will be deprecated:

- A yellow banner indicates the deprecation status
- When creating a job from the process page, you'll be prompted to:
  - **Create a tracked job** (recommended): Redirects to jobs page
  - **Process immediately**: Falls back to old behavior

**Timeline:**
- **Current**: Both workflows available
- **Next Quarter**: Process page will redirect to Jobs page
- **Future**: Process page will be removed

### Option 3: API Integration (Programmatic Access)

**Old API (Still Supported):**
```bash
# Single document processing
POST /api/v1/documents/{id}/process
```

**New API (Recommended):**
```bash
# Batch job creation
POST /api/v1/jobs
{
  "document_ids": ["doc-123", "doc-456"],
  "options": {
    "quality_thresholds": {...},
    "ocr_settings": {...}
  },
  "name": "My Batch Job",
  "start_immediately": true
}

# Monitor job
GET /api/v1/jobs/{job_id}

# Cancel job
POST /api/v1/jobs/{job_id}/cancel
```

---

## Feature Comparison

| Feature | Old Process Page | New Jobs System |
|---------|-----------------|-----------------|
| Batch Processing | ✅ Yes | ✅ Yes |
| Concurrent Batches | ❌ No | ✅ Yes (org limit) |
| Named Jobs | ❌ No | ✅ Yes |
| Job History | ❌ No | ✅ Yes |
| Real-time Logs | ⚠️ Limited | ✅ Full logs |
| Job Cancellation | ❌ No | ✅ With verification |
| Retention Policy | ❌ Manual | ✅ Automatic |
| Admin Statistics | ❌ No | ✅ Org-wide metrics |
| Document Status | ⚠️ Basic | ✅ Detailed |
| Resume Processing | ❌ No | ✅ Yes |

---

## Configuration Changes

### New Environment Variables

Add to your `.env` file (or use defaults):

```bash
# Job Management Configuration
DEFAULT_JOB_CONCURRENCY_LIMIT=3        # Max concurrent jobs per org
DEFAULT_JOB_RETENTION_DAYS=30          # Auto-cleanup after 30 days
JOB_CLEANUP_ENABLED=true               # Enable automatic cleanup
JOB_CLEANUP_SCHEDULE_CRON=0 3 * * *   # Daily at 3 AM UTC
JOB_CANCELLATION_TIMEOUT=30            # Cancellation verification timeout
JOB_STATUS_POLL_INTERVAL=2             # Frontend polling interval (seconds)
```

### Admin Settings

Administrators can configure job management settings via the **Settings → Job Management** tab:

1. **Concurrent Job Limit** (1-10): Max simultaneous jobs per organization
2. **Job Retention Period**: 7/30/90 days or indefinite
3. **Default Processing Options**: Organization-wide defaults

Changes take effect immediately for new jobs (running jobs continue with original settings).

---

## Step-by-Step Migration

### For End Users

1. **Familiarize Yourself with Jobs Page**
   - Navigate to `/jobs` in your browser
   - Explore the job list view and filters
   - Review example job detail pages

2. **Create Your First Job**
   - Click **Create New Job**
   - Upload or select files
   - Configure processing options
   - Name your job (e.g., "Q4 Financial Reports")
   - Start processing and monitor progress

3. **Explore Job History**
   - Filter jobs by status (Running, Completed, Failed)
   - Sort by creation date or name
   - Review past job results and logs

4. **Bookmark Key Pages**
   - Jobs list: `/jobs`
   - Job detail: `/jobs/[id]`
   - Admin settings: `/settings-admin` (admins only)

### For Administrators

1. **Review Organization Settings**
   - Navigate to **Settings → Job Management**
   - Set appropriate concurrency limits based on resources
   - Configure retention policies per compliance requirements

2. **Monitor Organization Metrics**
   - View real-time job statistics widget
   - Track active jobs vs. concurrency limit
   - Review success rates and performance metrics

3. **Communicate with Team**
   - Share this migration guide with users
   - Announce deprecation timeline for process page
   - Provide training on new jobs workflow

4. **Set Up Alerts (Optional)**
   - Monitor concurrency limits approaching maximum
   - Track job failure rates
   - Review storage usage trends

### For API Users

1. **Update API Calls**
   - Replace single-document processing with batch jobs
   - Use `/api/v1/jobs` endpoints instead of `/api/v1/documents/{id}/process`
   - Add job naming and description for better tracking

2. **Implement Polling**
   - Poll `/api/v1/jobs/{id}` for status updates
   - Handle job lifecycle states (PENDING, QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED)
   - Parse document-level status from job details

3. **Handle Errors Gracefully**
   - Respect concurrency limits (409 Conflict response)
   - Implement retry logic with exponential backoff
   - Check job logs for detailed error messages

4. **Test Thoroughly**
   - Validate job creation with various document sets
   - Test cancellation and cleanup behavior
   - Verify retention policy alignment with your needs

---

## Troubleshooting

### Common Issues

#### Issue: "Cannot create job - concurrency limit reached"

**Cause:** Your organization has reached its concurrent job limit.

**Solutions:**
1. Wait for active jobs to complete
2. Cancel unnecessary jobs to free up capacity
3. Contact an admin to increase the concurrency limit
4. Review job logs to identify stuck jobs

#### Issue: "Process page shows deprecation notice"

**Cause:** The process page is deprecated in favor of the jobs system.

**Solutions:**
1. Click **Try Jobs Page** button to navigate to new workflow
2. Update bookmarks to `/jobs` instead of `/process`
3. Familiarize yourself with the jobs interface

#### Issue: "Old job results are missing"

**Cause:** Job retention policy has cleaned up expired jobs.

**Solutions:**
1. Download results before jobs expire (check retention policy)
2. Request admin to adjust retention period if needed
3. Use file storage backups for long-term archival

#### Issue: "Job stuck in RUNNING state"

**Cause:** Worker may have crashed or job is genuinely long-running.

**Solutions:**
1. Check job logs for recent activity
2. Wait for worker health check timeout (automatic recovery)
3. Cancel job if truly stuck
4. Contact support if issue persists

#### Issue: "Cannot cancel job"

**Cause:** Job is in terminal state (COMPLETED, FAILED, CANCELLED) or permission denied.

**Solutions:**
1. Verify job is in RUNNING state
2. Ensure you have permission (job owner or admin)
3. Check job logs for cancellation attempts
4. Manually delete job if in terminal state (admin only)

---

## FAQ

### Will my old processing results be lost?

No, existing processed files remain in storage. Only new processing runs use the jobs system. Old results can be accessed via the storage API or file system.

### Can I still use the old process page?

Yes, temporarily. The process page will show a deprecation notice but remains functional. However, we recommend migrating to the jobs system for better tracking and features.

### How long will jobs be retained?

By default, completed jobs are retained for 30 days before automatic cleanup. Admins can configure retention policies per organization (7/30/90 days or indefinite).

### What happens if I exceed the concurrency limit?

Job creation will fail with a 409 Conflict error. Wait for active jobs to complete, or contact an admin to increase the limit. The system prevents resource exhaustion and ensures fair sharing.

### Can I process a single document?

Yes, create a job with a single document. The jobs system supports both single-document and batch processing. Single-document jobs are just as easy to create as batch jobs.

### How do I monitor organization-wide job activity?

Administrators can view org-wide metrics in **Settings → Job Management**. The statistics widget shows:
- Active jobs / concurrency limit
- Total jobs (24h/7d/30d)
- Average processing time
- Success rate percentage
- Storage usage

### Will API clients break?

No, the old document processing endpoints remain functional and create single-document jobs internally. However, we recommend migrating to the new `/api/v1/jobs` endpoints for better control and tracking.

### Can jobs be scheduled or automated?

Not yet, but this is planned for a future release. Currently, jobs must be created manually via the UI or API. Scheduled jobs and job templates are on the roadmap.

---

## Support

For questions or issues during migration:

1. **Review Documentation**:
   - [README.md](./README.md) - Quick start and overview
   - [CLAUDE.md](./CLAUDE.md) - Development guide and API reference
   - [USER_GUIDE.md](./USER_GUIDE.md) - End-user documentation

2. **Contact Support**:
   - Open an issue in the repository
   - Contact your system administrator
   - Reach out to the development team

3. **Provide Feedback**:
   - Report bugs or usability issues
   - Suggest improvements to the jobs workflow
   - Share your migration experience

---

## Checklist

Use this checklist to track your migration progress:

### End Users

- [ ] Navigate to `/jobs` page and explore interface
- [ ] Create first job using the Create Job Panel
- [ ] Monitor job progress in real-time
- [ ] Download results from completed job
- [ ] Review job history and filters
- [ ] Update bookmarks from `/process` to `/jobs`
- [ ] Learn keyboard shortcuts (`Cmd/Ctrl + J`)

### Administrators

- [ ] Review organization job settings in admin panel
- [ ] Set appropriate concurrency limits
- [ ] Configure retention policies per compliance needs
- [ ] Monitor organization job statistics
- [ ] Communicate migration plan to users
- [ ] Share this migration guide with team
- [ ] Plan process page deprecation timeline

### API Users

- [ ] Review new `/api/v1/jobs` endpoints
- [ ] Update API integration to use job creation
- [ ] Implement job status polling
- [ ] Handle concurrency limit errors
- [ ] Test job cancellation workflow
- [ ] Validate retention policy compatibility
- [ ] Update API documentation

---

## Additional Resources

- **API Documentation**: http://localhost:8000/docs (interactive)
- **GitHub Issues**: Report bugs or request features
- **Development Guide**: [CLAUDE.md](./CLAUDE.md)
- **Admin Setup**: [ADMIN_SETUP.md](./ADMIN_SETUP.md)
- **Deployment Guide**: [DEPLOYMENT_GUIDE.md](./DEPLOYMENT_GUIDE.md)

---

**Last Updated**: 2026-01-16

**Version**: Curatore v2.1.0 (Job Management System)
