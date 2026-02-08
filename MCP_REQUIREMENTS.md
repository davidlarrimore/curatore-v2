# Curatore MCP Gateway

### Architecture & Implementation Whitepaper

---

# 1. Purpose

The Curatore MCP Gateway is a standalone service that exposes a curated subset of Curatore’s CWR functions as MCP-compatible tools.

It serves as:

* The integration layer for Open WebUI
* The public tool interface for LLM tool use
* A policy enforcement boundary
* A contract validator
* An org-scoped execution proxy

It does **not**:

* Execute workflows internally
* Access Postgres directly
* Own business logic
* Replace CWR
* Replace backend APIs

It is a projection layer.

---

# 2. Architectural Positioning

## Current Services (simplified)

* curatore-backend (FastAPI)
* curatore-worker (Celery)
* curatore-beat
* curatore-extraction
* curatore-playwright
* redis
* postgres
* minio
* frontend

## New Service

Service name: `mcp`
Container name: `curatore-mcp`

It runs as a sibling container.

---

## Topology

```
Open WebUI
    ↓ MCP
curatore-mcp
    ↓ HTTP
curatore-backend (CWR + Data Core)
    ↓
Postgres / Redis / MinIO
```

The MCP service only talks to backend over HTTP.

---

# 3. Responsibilities

## 3.1 Tool Discovery

Implements MCP `tools/list`.

Steps:

1. Fetch ToolContractPack from CWR endpoint:
   GET /api/v1/cwr/contracts
2. Apply allowlist policy
3. Convert contracts into MCP tool definitions
4. Return MCP-compatible JSON

Contracts are the source of truth.

---

## 3.2 Tool Execution

Implements MCP `tools/call`.

Execution flow:

1. Authenticate request (API key or token)
2. Resolve org_id
3. Load contract for tool
4. Validate inputs against JSON Schema
5. Apply policy clamps
6. Inject org_id
7. Call backend:
   POST /api/v1/cwr/functions/{name}/execute
8. Return result in MCP format

---

## 3.3 Policy Enforcement Layer

Policy overlays contract.

Examples:

| Tool             | Contract Allows       | Policy Allows         |
| ---------------- | --------------------- | --------------------- |
| search_assets    | limit: 1000           | limit ≤ 50            |
| materialize_text | max_total_chars: 500k | max_total_chars ≤ 80k |
| llm_summarize    | max_tokens: 8000      | max_tokens ≤ 2000     |

Policy must override user input.

Policy file stored locally in service:
`policy.yaml`

---

# 4. Integration with CWR

## 4.1 Required CWR Endpoints

CWR must expose:

1. Tool contracts
   GET /api/v1/cwr/contracts

2. Execute tool
   POST /api/v1/cwr/functions/{tool}/execute

3. Metadata catalog
   GET /api/v1/data/metadata/catalog

4. Facet registry
   GET /api/v1/data/metadata/facets

These are read-only and execution endpoints.

---

## 4.2 Contract Structure Requirements

Each CWR tool must include:

* name
* description
* JSON Schema input
* Output schema
* Category
* Side-effect flag

Example (conceptual):

```
{
  "name": "search_assets",
  "description": "Search organization assets",
  "input_schema": { JSON Schema },
  "side_effect": false
}
```

If a tool has side_effect=true, MCP gateway should not expose it in MVP.

---

# 5. Org Context Resolution

## MVP

Single API key → maps to Default org.

Environment variable:

```
MCP_API_KEY=abc123
DEFAULT_ORG_ID=<uuid>
```

Gateway verifies header:
`Authorization: Bearer abc123`

Resolves org_id to DEFAULT_ORG_ID.

---

## Future

Support per-user mapping:

* validate JWT
* call backend identity endpoint
* derive org context dynamically

Not required for MVP.

---

# 6. Metadata Catalog & Facet Awareness

Gateway must:

1. Load metadata catalog per org
2. Cache for TTL (10 min)
3. Validate facet_filters against catalog
4. Reject unknown facet names

Example enforcement:

If model calls:

```
facet_filters:
  custom:
    fake_field: "value"
```

Gateway must reject.

This prevents hallucinated metadata use.

---

# 7. MCP Implementation Requirements

## Supported MCP Methods

* initialize
* tools/list
* tools/call

No need to support:

* resources
* prompts
* advanced streaming initially

---

## Transport

Use HTTP/SSE transport for compatibility with Open WebUI.

Expose endpoint:

POST /mcp

Or structured under:

/mcp/tools/list
/mcp/tools/call

Follow MCP JSON-RPC format.

---

# 8. Docker Compose Integration

Add:

```
mcp:
  build:
    context: ./mcp
  container_name: curatore-mcp
  depends_on:
    - backend
    - redis
  environment:
    - CURATORE_BACKEND_URL=http://backend:8000
    - REDIS_URL=redis://redis:6379/2
    - MCP_API_KEY=abc123
    - DEFAULT_ORG_ID=...
  ports:
    - "8020:8020"
```

Do not connect to postgres.

---

# 9. Tool Allowlist

Initial tool exposure (all safe functions without side effects):

**Search Functions (thin payload - return IDs/scores):**
* search_assets
* search_notices
* search_solicitations
* search_forecasts
* search_scraped_assets
* search_salesforce

**Content Retrieval (full payload):**
* get_asset
* get_content (formerly materialize_text)
* get
* query_model

**LLM Functions:**
* llm_summarize
* llm_extract
* llm_classify
* llm_generate

**Compound Functions (safe, read-only):**
* analyze_solicitation
* classify_document

Exclude (side effects):

* send_email
* webhook
* update_metadata
* bulk_update_metadata
* create_artifact

Side-effect tools require separate profile.

---

# 10. Observability

Gateway must log:

* tool_name
* org_id
* duration
* input size
* output size
* success/failure
* validation errors

Add correlation ID forwarded to backend.

---

# 11. Failure Handling

### Validation Error

Return MCP error:

* code: INVALID_ARGUMENT
* message: JSON Schema validation failure

### Policy Violation

Return MCP error:

* code: POLICY_VIOLATION
* message: Limit exceeds allowed maximum

### Backend Failure

Return:

* code: EXECUTION_ERROR
* include backend message

Never crash container.

---

# 12. Testing Plan

## Phase 1 – Protocol

* Connect Open WebUI
* Confirm tools appear

## Phase 2 – Execution

* Run search_assets limit 3
* Run materialize_text top_k 2
* Run llm_summarize

## Phase 3 – Negative

* limit 500 → clamped
* invalid facet → rejected
* missing required param → rejected

---

# 13. Security Requirements

* Require API key or JWT
* Do not expose backend URL publicly
* Disable side-effect tools
* Enforce payload size caps
* Rate limit per IP

---

# 14. Non-Goals

MCP Gateway does NOT:

* Compile procedures
* Run stored procedures
* Replace CWR
* Replace Celery
* Own metadata

It is a stateless projection layer with caching.

---

# 15. Success Criteria

The MCP integration is successful when:

1. Open WebUI discovers tools
2. Tool calls succeed deterministically
3. Invalid inputs fail cleanly
4. Facet hallucinations are rejected
5. Payload limits are enforced
6. Gateway never accesses DB directly

---

# 16. Long-Term Evolution

Once stable:

* Add profile-based tool exposure
* Add per-user auth
* Add procedure draft tool
* Add write-capable tool set (admin profile)
* Add audit export

---

# Summary

The Curatore MCP Gateway is:

* A thin container
* A contract validator
* A policy enforcer
* A tool execution proxy
* An org-scoped adapter
* The clean boundary between Open WebUI and CWR

It keeps CWR pure and deterministic while allowing Open WebUI to safely use Curatore as a tool system.
