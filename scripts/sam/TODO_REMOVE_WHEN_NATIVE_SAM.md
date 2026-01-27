# TODO: Remove SAM.gov External Script Infrastructure

⚠️  **ACTION REQUIRED WHEN NATIVE SAM.GOV INTEGRATION IS IMPLEMENTED**

This file lists all temporary code that must be removed when native SAM.gov
integration is built into the Curatore backend/frontend.

## Removal Checklist

### 1. Remove External Scripts
- [ ] Delete `/scripts/sam/backend_upload.py`
- [ ] Delete `/scripts/sam/sam_pull.py`
- [ ] Delete `/scripts/sam/MIGRATION_GUIDE.md`
- [ ] Delete `/scripts/sam/TODO_REMOVE_WHEN_NATIVE_SAM.md` (this file)
- [ ] Remove entire `/scripts/sam/` directory if empty

### 2. Remove Backend API Endpoints
Edit `/backend/app/api/v1/routers/storage.py`:
- [ ] Remove `POST /upload/proxy` endpoint (lines ~174-279)
- [ ] Remove `GET /download/{document_id}/proxy` endpoint (lines ~292-360)
- [ ] Remove `GET /object/download` proxy endpoint (lines ~1325-1390)
- [ ] Remove "TEMPORARY PROXY ENDPOINTS" section from module docstring (lines ~17-32)
- [ ] Update module docstring to remove references to SAM.gov scripts

### 3. Clean Up Documentation
- [ ] Remove SAM.gov script references from `/CLAUDE.md`
- [ ] Update system architecture documentation
- [ ] Add native SAM.gov integration documentation
- [ ] Archive migration guide for historical reference

### 4. Update Dependencies
- [ ] Remove `requests>=2.31.0` from `backend/requirements.txt` (line 14)
  - This was added temporarily for SAM script's backend_upload.py
  - Backend uses `httpx` for async HTTP, `requests` is only for SAM scripts
- [ ] Delete `scripts/sam/requirements.txt`
- [ ] Review if any other dependencies were added solely for SAM scripts

### 5. Database Cleanup (Optional)
- [ ] Consider migrating existing SAM.gov uploaded documents to new system
- [ ] Update metadata to reflect native import source
- [ ] Clean up old artifact records if needed

### 6. Frontend Updates
- [ ] Ensure storage browser works without proxy endpoints
- [ ] Verify file upload/download flows use standard endpoints
- [ ] Test job creation with SAM-imported files

## Replacement Features to Implement

Before removing the external scripts, ensure these native features are implemented:

### Backend Features
- [ ] `POST /api/v1/sam/sync` - Sync opportunities from SAM.gov API
- [ ] `GET /api/v1/sam/opportunities` - List synced opportunities
- [ ] `POST /api/v1/sam/opportunities/{id}/import` - Import opportunity files
- [ ] `GET /api/v1/sam/config` - SAM.gov connection configuration
- [ ] Background job for scheduled sync
- [ ] Opportunity metadata storage in database
- [ ] File import with automatic artifact creation

### Frontend Features
- [ ] `/sam` page - SAM.gov opportunity browser
- [ ] `/sam/settings` page - Connection and sync configuration
- [ ] `/sam/opportunities/{id}` page - Opportunity detail with file import
- [ ] Real-time sync status indicators
- [ ] Notification system for new opportunities
- [ ] One-click file import with processing

### Testing Requirements
- [ ] Test SAM.gov API connectivity
- [ ] Test opportunity sync
- [ ] Test file import from opportunities
- [ ] Test metadata preservation
- [ ] Test processing jobs with SAM-imported files
- [ ] End-to-end workflow testing

## Verification Steps

Before marking this task as complete:

1. **Verify no references remain**:
   ```bash
   # Search for references to backend_upload
   grep -r "backend_upload" backend/ frontend/ scripts/

   # Search for references to proxy endpoints
   grep -r "upload/proxy\|download.*proxy\|object/download" frontend/

   # Search for SAM script references
   grep -r "sam_pull\|scripts/sam" .
   ```

2. **Test native workflows**:
   - Sync opportunities from SAM.gov API
   - Import files from an opportunity
   - Create processing job with imported files
   - Verify metadata is preserved

3. **Update documentation**:
   - Remove all references to external SAM scripts
   - Document native SAM.gov integration
   - Update API documentation

4. **Clean up codebase**:
   - Remove commented-out code
   - Update module docstrings
   - Remove temporary TODOs

## Notes

- **Priority**: This cleanup should be done as soon as native SAM integration is ready
- **Risk**: Low - these are isolated external scripts that don't affect core functionality
- **Effort**: ~2-4 hours for complete cleanup and verification
- **Dependencies**: Requires native SAM.gov integration to be fully implemented and tested

## Questions or Issues?

If you encounter any issues during removal:
1. Check git history for context on why each piece was added
2. Review MIGRATION_GUIDE.md for original implementation details
3. Test thoroughly before removing production code
4. Keep this file until all items are verified removed

---

**Created**: 2026-01-27
**Reason**: Temporary workaround for SAM.gov file imports until native integration is built
**Owner**: Development team responsible for SAM.gov integration feature
