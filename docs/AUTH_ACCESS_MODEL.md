# Authentication & Access Model

Comprehensive reference for Curatore v2's authentication, authorization, and multi-org access model.

## Roles & Permissions Matrix

| Role | Scope | Organization | Data Access | CWR Functions | Procedures | System Config |
|------|-------|-------------|-------------|---------------|------------|---------------|
| `admin` | System-wide | `organization_id=NULL`, accesses orgs via `X-Organization-Id` header | All orgs (cross-org in system context, filtered in org context) | All (including side-effect tools); system context sees all tools regardless of data sources | Full CRUD + `admin_full` generation profile + system procedures | Full (services, connections, LLM, orgs) |
| `member` | Single org | `organization_id=<org_uuid>` | Own org only | All (including side-effect tools); filtered by org's enabled data sources | Run + `workflow_standard` generation profile | None |

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
| `get_current_user` | `User` | Authenticated user (JWT or user API key). |
| `get_effective_org_id` | `Optional[UUID]` | Cross-org admin views (ops dashboards). Returns `None` for admin system context, UUID for org-scoped context. |
| `get_current_org_id` | `UUID` (required) | Org-scoped data operations. Raises 400 if no org context available. |
| `require_admin` | `User` | System admin only (raises 403 otherwise). |
| `get_current_user_or_delegated` | `User` | Flexible auth: JWT, user API key, or delegated (ServiceAccount + X-On-Behalf-Of). Used by CWR endpoints. |
| `get_effective_org_id_or_delegated` | `Optional[UUID]` | Cross-org views with delegated auth support. |
| `get_current_org_id_or_delegated` | `UUID` (required) | Org-scoped operations with delegated auth support. |

**Implementation rule**: ALWAYS use `get_current_org_id` or `get_effective_org_id` (or their `_or_delegated` variants for CWR endpoints) — NEVER `current_user.organization_id` directly.

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
- **Side-effect tools**: All authenticated users can execute side-effect functions. No role gate is applied.
- Runtime execution also checks `required_data_sources` as defense-in-depth (403 if disabled)

### Generation Profiles
Profiles are server-enforced by role when generating procedures via AI:

| Role | Max Profile | Description |
|------|-------------|-------------|
| `admin` | `admin_full` | All tools available including dangerous/destructive |
| `member` | `workflow_standard` | Standard workflow tools (excludes webhook, bulk updates) |

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

The MCP Gateway uses **delegated authentication** to propagate per-user identity from Open WebUI (or other clients) to the backend.

### Auth Chain

```
Client → MCP Gateway:   Authorization: Bearer <SERVICE_API_KEY>
                         X-OpenWebUI-User-Email: alice@company.com

MCP Gateway → Backend:   X-API-Key: <BACKEND_API_KEY>      (ServiceAccount key)
                         X-On-Behalf-Of: alice@company.com  (user identity)
```

### How It Works

1. The MCP Gateway authenticates incoming requests using `SERVICE_API_KEY` (shared secret with Open WebUI)
2. It extracts the user's email from the `X-OpenWebUI-User-Email` header
3. It forwards the request to the backend with the `BACKEND_API_KEY` (a ServiceAccount API key) and `X-On-Behalf-Of` header
4. The backend's `get_delegated_user` dependency validates the ServiceAccount key and resolves the Curatore user by email
5. All data is scoped to the resolved user's organization

### Dependencies

| Dependency | Returns | Use Case |
|-----------|---------|----------|
| `get_delegated_user` | `User` | ServiceAccount key + X-On-Behalf-Of email → resolved user |
| `get_current_user_or_delegated` | `User` | Flexible auth: JWT, user API key, or delegated (used by CWR endpoints) |
| `get_effective_org_id_or_delegated` | `Optional[UUID]` | Org resolution with delegated auth support |
| `get_current_org_id_or_delegated` | `UUID` | Org-scoped operations with delegated auth support |

### Requirements

- Open WebUI must set `ENABLE_FORWARD_USER_INFO_HEADERS=true`
- Each Open WebUI user must have a matching Curatore user account (same email)
- A ServiceAccount must be created in Curatore; its API key is used as `BACKEND_API_KEY`
- Side-effect gating is handled at the MCP policy level (`policy.yaml` allowlist)

See [MCP & Open WebUI Guide](MCP_OPEN_WEBUI.md) for the full setup walkthrough.

---

## Implementation Rules for New Endpoints

1. **ALWAYS** use `get_current_org_id` or `get_effective_org_id` — NEVER `current_user.organization_id`
2. Use `get_effective_org_id` (`Optional`) for cross-org admin views (ops dashboards, metrics)
3. Use `get_current_org_id` (required) for org-scoped data operations (create, update, delete)
4. Admin access checks: `if user.role != "admin" and resource.organization_id != org_id`
5. Side-effect functions: available to all authenticated users
6. System procedure editing: require `admin` role
7. Registration: exclude `__system__` org from default org selection
8. Role demotion: when demoting from `admin`, require an org context for the new assignment
