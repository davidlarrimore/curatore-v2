# Authentication & Access Model

Comprehensive reference for Curatore v2's authentication, authorization, and multi-org access model.

## Roles & Permissions Matrix

| Role | Scope | Organization | Data Access | CWR Functions | Procedures | System Config |
|------|-------|-------------|-------------|---------------|------------|---------------|
| `admin` | System-wide | `organization_id=NULL`, accesses orgs via `X-Organization-Id` header | All orgs (cross-org in system context, filtered in org context) | All (including side-effect tools); system context sees all tools regardless of data sources | Full CRUD + `admin_full` generation profile + system procedures | Full (services, connections, LLM, orgs) |
| `org_admin` | Single org | `organization_id=<org_uuid>` | Own org only | All except org_admin-blocked tools; filtered by org's enabled data sources | Full CRUD + `workflow_standard` generation profile | Org-level settings only |
| `member` | Single org | `organization_id=<org_uuid>` | Own org only | Read-only (no side-effect tools); filtered by org's enabled data sources | Run only (cannot create/edit) | None |
| `viewer` | Single org | `organization_id=<org_uuid>` | Own org read-only | Read-only (no side-effect tools); filtered by org's enabled data sources | View only | None |

---

## Organization Context Resolution

### Admin Users (`role="admin"`)
- Have `organization_id=NULL` in the database
- Access any org via the `X-Organization-Id` HTTP header
- **System context** (no header): cross-org view — ops dashboards show ALL data
- **Org context** (with header): filtered view — data scoped to the selected org

### Non-Admin Users
- Always scoped to their `user.organization_id`
- The `X-Organization-Id` header is ignored
- Cannot view or modify data from other organizations

### Dependencies

| Dependency | Returns | Use Case |
|-----------|---------|----------|
| `get_effective_org_id` | `Optional[UUID]` | Cross-org admin views (ops dashboards). Returns `None` for admin system context, UUID for org-scoped context. |
| `get_current_org_id` | `UUID` (required) | Org-scoped data operations. Raises 400 if no org context available. |
| `get_current_user` | `User` | Authenticated user object. |
| `require_admin` | `User` | System admin only (raises 403 otherwise). |
| `require_org_admin_or_above` | `User` | `org_admin` or `admin` role (raises 403 otherwise). |
| `require_org_admin` | `User` | `org_admin` only — NOT admin (raises 403 otherwise). |

**Implementation rule**: ALWAYS use `get_current_org_id` or `get_effective_org_id` — NEVER `current_user.organization_id` directly.

---

## System Organization (`__system__`)

- Slug: `__system__`, defined as `SYSTEM_ORG_SLUG` in `app.config`
- Used ONLY for CWR procedure/pipeline ownership (system-level procedures)
- NOT used for admin user assignment (admins have `organization_id=NULL`)
- Excluded from all user-facing org lists
- Excluded from registration default org selection
- Users cannot be assigned to it

---

## CWR Access Model

### Function Execution
- **Org data source filtering**: Functions that declare `required_data_sources` are hidden from orgs that haven't enabled those sources (404 on detail, excluded from listings). System context (`org_id=None`) sees all.
- **Side-effect gating**: Functions with `side_effects=True` require `org_admin` or `admin` role
- Non-privileged users (member, viewer) receive 403 when attempting to execute side-effect functions
- Runtime execution also checks `required_data_sources` as defense-in-depth (403 if disabled)

### Generation Profiles
Profiles are server-enforced by role when generating procedures via AI:

| Role | Max Profile | Description |
|------|-------------|-------------|
| `admin` | `admin_full` | All tools available including dangerous/destructive |
| `org_admin` | `workflow_standard` | Standard workflow tools (excludes webhook, bulk updates) |
| `member` / `viewer` | `safe_readonly` | Read-only tools only |

If a user requests a profile above their cap, the server silently downgrades to their maximum.

In addition to profile-based filtering, the AI generator filters by the org's enabled data sources. Functions whose `required_data_sources` are not active for the org are excluded from the contract pack before the LLM sees them. System context (admin with no org) sees all tools.

### Procedure CRUD
- **Create/Edit**: Requires authentication (`get_current_user`)
- **System procedure editing**: Requires `admin` role
- **Run**: Available to users with appropriate access
- **View**: Available to all authenticated users

### Runtime Permissions
Approved procedures run with full permissions at execution time, regardless of the triggering user's role. This is by design — procedures are pre-approved workflows.

---

## Admin Access Patterns

### Cross-Org View (Ops Dashboards)
```python
@router.get("/runs")
async def list_runs(
    org_id: Optional[UUID] = Depends(get_effective_org_id),
    current_user: User = Depends(get_current_user),
):
    conditions = [...]
    if org_id is not None:
        conditions.append(Run.organization_id == org_id)
    # When org_id is None → admin sees ALL orgs
```

### Admin Bypass for Single-Resource Access
```python
@router.get("/runs/{run_id}")
async def get_run(
    run_id: UUID,
    org_id: Optional[UUID] = Depends(get_effective_org_id),
    current_user: User = Depends(get_current_user),
):
    run = await fetch_run(run_id)
    if current_user.role != "admin" and run.organization_id != org_id:
        raise HTTPException(403, "Access denied")
```

### Org-Required Operations
```python
@router.post("/api-keys")
async def create_api_key(
    request: ApiKeyCreateRequest,
    current_user: User = Depends(get_current_user),
    org_id: UUID = Depends(get_current_org_id),  # Raises 400 if no org
):
    # API keys are org-scoped, so org context is required
```

---

## MCP Gateway Access

- **Current**: Shared API key authentication, no per-user identity
- **Known limitation**: No RBAC in the MCP layer
- Side-effect gating is handled at the MCP policy level (`policy.yaml` allowlist)
- Future work: Per-user MCP authentication with role propagation

---

## Implementation Rules for New Endpoints

1. **ALWAYS** use `get_current_org_id` or `get_effective_org_id` — NEVER `current_user.organization_id`
2. Use `get_effective_org_id` (`Optional`) for cross-org admin views (ops dashboards, metrics)
3. Use `get_current_org_id` (required) for org-scoped data operations (create, update, delete)
4. Admin access checks: `if user.role != "admin" and resource.organization_id != org_id`
5. Side-effect functions: require `org_admin` or `admin` role
6. System procedure editing: require `admin` role
7. Registration: exclude `__system__` org from default org selection
8. Role demotion: when demoting from `admin`, require an org context for the new assignment
