# Storage Cleanup Utility

When making breaking changes to the storage layer during development, use the storage cleanup utility to reset object storage and artifact records.

## Overview

The cleanup utility:
- **Deletes objects** from MinIO/S3 buckets
- **Removes artifact records** from database
- **Resets asset file_hash values** to allow reprocessing
- **Recreates bucket structure** with lifecycle policies
- **Creates default organization folders** for immediate use
- **Supports scoped cleanup** (by organization or bucket)
- **Includes safety features** (dry-run, confirmation prompts)

## Quick Start

### Dry Run (See What Would Be Deleted)

```bash
./scripts/cleanup_storage.sh --dry-run
```

This shows what would be deleted without making any changes.

### Interactive Cleanup (With Confirmation)

```bash
./scripts/cleanup_storage.sh
```

Prompts for confirmation before deleting. Type `DELETE` to confirm.

### Force Cleanup (No Confirmation)

```bash
./scripts/cleanup_storage.sh --force
```

⚠️ **DANGEROUS** - Deletes immediately without prompting.

## Advanced Usage

### Clean Specific Bucket

```bash
./scripts/cleanup_storage.sh --bucket curatore-uploads
```

Only cleans the specified bucket and its artifact records.

### Clean Specific Organization

```bash
./scripts/cleanup_storage.sh --org-id 1542fe09-9ece-4a7a-8b48-5298ab510a03
```

Only cleans data for the specified organization.

### Skip Bucket Recreation

By default, the cleanup utility recreates buckets and organization folders after cleanup. To skip this:

```bash
./scripts/cleanup_storage.sh --skip-recreate
```

This is useful if you want to manually recreate the structure or are troubleshooting bucket issues.

### Combine Options

```bash
# Dry run for specific bucket
./scripts/cleanup_storage.sh --dry-run --bucket curatore-temp

# Force cleanup specific org
./scripts/cleanup_storage.sh --force --org-id <uuid>

# Cleanup without recreation
./scripts/cleanup_storage.sh --force --skip-recreate
```

## Python Command (Alternative)

You can also run the Python command directly:

```bash
cd backend
source .venv/bin/activate
python -m app.commands.cleanup_storage --help
```

## When to Use

Use this cleanup utility when:

1. **Making storage structure changes** - Reorganizing bucket layout or object keys
2. **Breaking artifact references** - Changing how files are tracked in database
3. **Changing extraction methods** - Need to reset and reprocess all documents
4. **Development resets** - Starting fresh after testing breaking changes
5. **Storage inconsistencies** - Fixing mismatches between storage and database

## What Happens During Cleanup

### Phase 1: Cleanup (Destructive)

**Object Storage (MinIO/S3)**:
- All objects in `curatore-uploads` bucket (uploaded files)
- All objects in `curatore-processed` bucket (processed markdown)
- All objects in `curatore-temp` bucket (temporary files)

**Database**:
- All `Artifact` records (tracks stored files)
- `Asset.file_hash` values reset to NULL (allows reprocessing)

### Phase 2: Recreation (Automatic)

**Buckets Recreated**:
- `curatore-uploads` with 30-day lifecycle policy
- `curatore-processed` with 90-day lifecycle policy
- `curatore-temp` with 7-day lifecycle policy

**Organization Folders Created**:
- Default organization folder structure in each bucket
- `.keep` files to establish folder paths
- Ready for immediate document uploads

### What's Preserved

**Always Preserved**:
- `Asset` records (document metadata)
- `AssetVersion` records (version history)
- `Organization` and `User` records
- All other database tables

**Note**: Use `--skip-recreate` to prevent bucket recreation if desired.

## Safety Features

### Confirmation Prompt

When running interactively, you'll see:

```
⚠️  DESTRUCTIVE OPERATION - STORAGE CLEANUP
======================================================================
  Scope: ALL organizations and buckets

  This will DELETE:
    • All objects in MinIO/S3 storage (within scope)
    • All artifact records from database
    • Asset file_hash values will be set to NULL

  This operation CANNOT be undone!
======================================================================

  Type 'DELETE' to confirm:
```

### Dry Run Mode

Always test with `--dry-run` first to see what would be deleted:

```bash
./scripts/cleanup_storage.sh --dry-run
```

Output shows:
```
[DRY RUN] Would delete: curatore-uploads/org-id/doc-id/uploaded/file.pdf
[DRY RUN] Would delete 150 artifact records
[DRY RUN] Would reset file_hash for 75 assets
```

## Example Workflow

### Before Making Breaking Storage Changes

1. **Check current state**:
   ```bash
   ./scripts/cleanup_storage.sh --dry-run
   ```

2. **Make your code changes** to storage structure

3. **Clean up old data and recreate structure**:
   ```bash
   ./scripts/cleanup_storage.sh
   # Type 'DELETE' to confirm
   # Buckets and folders automatically recreated
   ```

4. **Test new implementation** with fresh uploads
   - Storage is ready to use immediately
   - Default organization folders already created
   - Lifecycle policies already configured

### After Storage Becomes Inconsistent

If bulk upload or asset operations fail with storage errors:

1. **Check what's in storage**:
   ```bash
   ./scripts/cleanup_storage.sh --dry-run
   ```

2. **Clean and reset**:
   ```bash
   ./scripts/cleanup_storage.sh --force
   ```

3. **Re-upload test documents**

## Scoped Cleanup Strategies

### Clean Only Temp Files

Good for cleaning up after failed processing:

```bash
./scripts/cleanup_storage.sh --bucket curatore-temp --force
```

### Clean Test Organization

If you have a test organization for development:

```bash
./scripts/cleanup_storage.sh --org-id <test-org-id> --force
```

### Full Reset (All Storage)

Complete clean slate:

```bash
./scripts/cleanup_storage.sh --force
```

## Best Practices

1. **Always dry-run first** - See what will be deleted
2. **Use scoped cleanup** - Limit to specific bucket/org when possible
3. **Backup production** - Never run against production data without backup
4. **Document changes** - Note why cleanup was needed for future reference
5. **Test after cleanup** - Verify new implementation works with fresh data

## Troubleshooting

### "MinIO is not enabled"

Check environment variables:
```bash
grep MINIO .env
```

Ensure `USE_OBJECT_STORAGE=true` and MinIO credentials are set.

### "Virtual environment not found"

Create and activate venv:
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Permission Errors

Ensure MinIO credentials have delete permissions:
- `s3:DeleteObject` permission on all buckets
- Or use admin credentials during development

## Related Documentation

- [Storage Architecture](../CLAUDE.md#file-storage) - Object storage setup
- [Architecture Refactor Progress](../ARCHITECTURE_PROGRESS.md) - Current phase work
- [Data Architecture Spec](../UPDATED_DATA_ARCHITECTURE.md) - Storage requirements

## Notes

- This utility is **designed for development** use
- **Not suitable for production** without careful scoping
- Cleanup is **immediate and irreversible**
- Storage objects are **permanently deleted** (no recycle bin)
- Database changes are **committed immediately** (no rollback after commit)

---

**Remember**: This is a destructive operation. Always prefer `--dry-run` and scoped cleanup over full cleanup when possible.
