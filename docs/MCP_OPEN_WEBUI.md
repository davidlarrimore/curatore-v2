# MCP Gateway & Open WebUI Integration

This guide explains how to integrate Curatore with Open WebUI using the MCP Gateway.

---

## Overview

The Curatore MCP Gateway exposes CWR functions to AI assistants through **two protocols**:

| Protocol | Transport | Use Case |
|----------|-----------|----------|
| **MCP** (Model Context Protocol) | JSON-RPC over HTTP | Native MCP clients |
| **OpenAPI** | REST with OpenAPI spec | OpenAI-compatible clients |

Open WebUI supports both connection methods. Choose based on your preference:

| Method | Pros | Cons |
|--------|------|------|
| **MCP** | Native protocol, richer capabilities | Newer, less widely supported |
| **OpenAPI** | Widely compatible, familiar REST | Simpler protocol |

---

## Prerequisites

- Curatore v2 running with `docker-compose`
- Open WebUI installed and configured
- MCP Gateway running (port 8020)

---

## Setup

### Step 1: Create a ServiceAccount in Curatore

The MCP Gateway authenticates to the Curatore backend using a **ServiceAccount API key**. This is required for per-user identity propagation — the gateway forwards Open WebUI user identity so the backend can scope data to the correct organization.

1. Log in to Curatore as an admin
2. Navigate to **Settings** > **API Keys** > **Service Accounts**
3. Create a new ServiceAccount (e.g., name: "MCP Gateway")
4. Copy the generated API key (starts with `cur_`)

### Step 2: Configure Environment Variables

In your `.env` file, set both keys:

```bash
# Shared secret between Open WebUI and the MCP Gateway
# Clients (Open WebUI) must send this as: Authorization: Bearer <key>
# Leave empty for dev mode (all requests pass through without auth)
MCP_SERVICE_API_KEY=your_secure_shared_secret_here

# ServiceAccount API key for authenticating to the Curatore backend
# Created in Step 1 — the gateway sends this as X-API-Key to the backend
MCP_BACKEND_API_KEY=cur_abcdef1234567890
```

### Step 3: Start the MCP Gateway

```bash
docker-compose up -d mcp
```

Verify it's running:

```bash
curl http://localhost:8020/health
```

### Step 4: Configure Open WebUI

Open WebUI must forward per-user identity headers so the MCP Gateway can propagate user context to the backend.

**Required Open WebUI environment variable:**

```bash
ENABLE_FORWARD_USER_INFO_HEADERS=true
```

This tells Open WebUI to send user identity headers on every MCP tool call. The following headers are forwarded automatically:

| Header | Example | Used by Gateway |
|--------|---------|-----------------|
| `x-openwebui-user-email` | `alice@company.com` | Yes — forwarded as `X-On-Behalf-Of` |
| `x-openwebui-user-name` | `Alice Smith` | No (available for future use) |
| `x-openwebui-user-id` | `3d688e10-...` | No (available for future use) |
| `x-openwebui-user-role` | `admin` | No (available for future use) |
| `x-openwebui-chat-id` | `377f7274-...` | No |
| `x-openwebui-message-id` | `2fb66beb-...` | No |

**Add the MCP Gateway as a tool server in Open WebUI:**

1. Go to **Settings** > **Tools** > **MCP Servers**
2. Click **Add MCP Server**
3. Configure:

| Field | Value |
|-------|-------|
| Name | Curatore |
| Type | HTTP (Streamable) |
| URL | `http://host.docker.internal:8020/mcp` (see URL table below) |
| Headers | `{"Authorization": "Bearer YOUR_SERVICE_API_KEY"}` |

### How Identity Propagation Works

```
Open WebUI                         MCP Gateway                      Curatore Backend
    │                                  │                                  │
    │  Authorization: Bearer <SERVICE_API_KEY>                            │
    │  x-openwebui-user-email: alice@company.com                          │
    │─────────────────────────►│                                          │
    │                          │  X-API-Key: <BACKEND_API_KEY>            │
    │                          │  X-On-Behalf-Of: alice@company.com       │
    │                          │─────────────────────────►│               │
    │                          │                          │ Resolves user │
    │                          │                          │ by email,     │
    │                          │                          │ scopes data   │
    │                          │                          │ to user's org │
    │                          │◄─────────────────────────│               │
    │◄─────────────────────────│                                          │
```

**Key points:**
- Each Open WebUI user's email is forwarded to the backend automatically
- The backend resolves the Curatore user by email and scopes all data to that user's organization
- Open WebUI users **must have matching Curatore accounts** (same email address)
- If no matching Curatore user exists, the request returns 404

---

## Connection Method 1: MCP Protocol (Streamable HTTP)

Use this method if you want to connect via the native MCP protocol. This is the recommended method — the Step 4 configuration above uses this approach.

### URL by Deployment

| Open WebUI Setup | URL |
|------------------|-----|
| Host machine (not Docker) | `http://localhost:8020/mcp` |
| Docker (same machine as Curatore) | `http://host.docker.internal:8020/mcp` |
| Docker (same network as Curatore) | `http://mcp:8020/mcp` |

### How It Works

1. Open WebUI connects to `/mcp` endpoint
2. Sends JSON-RPC `initialize` request
3. Fetches tools via `tools/list`
4. Executes tools via `tools/call`

### MCP Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/mcp` | POST | MCP SDK Streamable HTTP transport (tools/list, tools/call, resources/list) |
| `/rest/tools` | GET | REST endpoint to list tools (for debugging) |
| `/rest/tools/{name}/call` | POST | REST endpoint to call a tool (for debugging) |

### Test MCP Connection

```bash
# List tools via REST convenience endpoint
curl -H "Authorization: Bearer YOUR_SERVICE_API_KEY" \
  http://localhost:8020/rest/tools

# Or use the OpenAI-compatible endpoint
curl -H "Authorization: Bearer YOUR_SERVICE_API_KEY" \
  http://localhost:8020/openai/tools
```

---

## Connection Method 2: OpenAPI

Use this method if you prefer standard REST/OpenAPI integration.

### Open WebUI Configuration

1. Go to **Settings** > **Tools** > **OpenAPI Servers**
2. Click **Add Server**
3. Configure:

| Field | Value |
|-------|-------|
| Name | Curatore |
| URL | See table below |
| Authentication | Bearer Token |
| Token | Your `MCP_SERVICE_API_KEY` value |

**URL by deployment:**

| Open WebUI Setup | URL |
|------------------|-----|
| Host machine (not Docker) | `http://localhost:8020` |
| Docker (same machine as Curatore) | `http://host.docker.internal:8020` |
| Docker (same network as Curatore) | `http://mcp:8020` |

**Note:** Do NOT include `/openapi.json` in the URL - Open WebUI appends it automatically.

### How It Works

1. Open WebUI fetches `GET /openapi.json` to discover tools
2. Each tool appears as a function the LLM can call
3. Tools are executed via `POST /{tool_name}` with JSON body

### OpenAPI Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/openapi.json` | GET | OpenAPI 3.0 specification (auto-generated) |
| `/{tool_name}` | POST | Execute a tool (e.g., `POST /search_assets`) |
| `/openai/tools` | GET | List tools in OpenAI function format |
| `/openai/tools/{name}` | POST | Execute tool (alternative path) |

### Test OpenAPI Connection

```bash
# Fetch OpenAPI spec
curl http://localhost:8020/openapi.json | jq '.paths | keys'

# List tools (OpenAI format)
curl -H "Authorization: Bearer YOUR_SERVICE_API_KEY" \
  http://localhost:8020/openai/tools | jq '.tools[].function.name'

# Execute a tool
curl -X POST http://localhost:8020/search_assets \
  -H "Authorization: Bearer YOUR_SERVICE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "contract management", "limit": 5}'
```

---

## Available Tools

Both connection methods expose the same tools, auto-derived from backend contracts with `exposure_profile.agent: true` (see `mcp/policy.yaml` for denylist overrides):

### Search Functions

| Tool | Description | Payload |
|------|-------------|---------|
| `search_assets` | Search organization documents | Thin |
| `search_notices` | Search SAM.gov notices | Thin |
| `search_solicitations` | Search SAM.gov solicitations | Thin |
| `search_forecasts` | Search acquisition forecasts | Thin |
| `search_scraped_assets` | Search web-scraped content | Thin |
| `search_salesforce` | Search Salesforce data | Thin |

**Note:** Thin payload = IDs, titles, scores. Use `get_content` to retrieve full text.

### Content Retrieval

| Tool | Description | Payload |
|------|-------------|---------|
| `get_asset` | Get asset metadata and content | Full |
| `get_content` | Get full text for multiple assets | Full |
| `get` | Generic get by ID | Full |
| `query_model` | Query database models | Full |

### LLM Functions

| Tool | Description |
|------|-------------|
| `llm_summarize` | Summarize text or documents |
| `llm_extract` | Extract structured data from text |
| `llm_classify` | Classify text into categories |
| `llm_generate` | Generate text from prompts |

### Compound Functions

| Tool | Description |
|------|-------------|
| `analyze_solicitation` | Analyze a SAM.gov solicitation |
| `classify_document` | Classify a document |

### Email Workflow (Two-Step)

For AI safety, email sending requires two-step confirmation:

| Tool | Description | Side Effects |
|------|-------------|--------------|
| `prepare_email` | Create email preview, returns confirmation token | No |
| `confirm_email` | Send email using confirmation token (15 min expiry) | Yes (allowed) |

**Example conversation:**
```
User: "Send a summary of document abc-123 to team@company.com"

AI: I'll prepare the email for you to review.
    [calls prepare_email]

AI: Here's the email preview:
    To: team@company.com
    Subject: Document Summary
    Body: [summary content]

    Would you like me to send this?

User: "Yes, send it"

AI: [calls confirm_email with token]
    Email sent successfully!
```

---

## Policy Configuration

The MCP Gateway enforces policies defined in `mcp/policy.yaml`:

### Auto-Derive Mode (v2.0)

Tools are automatically exposed based on their backend contract's `exposure_profile.agent` field. No allowlist needed — add a function to the backend with `agent: true` and it appears in MCP.

To block specific tools, add them to the **denylist**:

```yaml
version: "2.0"
denylist:
  - dangerous_function  # Block regardless of exposure_profile
```

### Side Effects Control

```yaml
settings:
  block_side_effects: true
  side_effects_allowlist:
    - confirm_email  # Allowed because it requires a token
```

### Parameter Clamps

Limits enforced on parameters:

| Tool | Parameter | Max | Default |
|------|-----------|-----|---------|
| `search_*` | `limit` | 50 | 20 |
| `get_content` | `max_total_chars` | 80,000 | 50,000 |
| `llm_*` | `max_tokens` | 2,000 | 1,000 |

---

## Troubleshooting

### Tools Not Appearing

1. Check gateway health: `curl http://localhost:8020/health`
2. Verify SERVICE_API_KEY is correct
3. Check logs: `docker logs curatore-mcp`

### "Tool not found" Errors

1. Check the function has `exposure_profile.agent: true` in its backend contract
2. Check the function is not in `policy.yaml` denylist
3. Verify tool doesn't have blocked side effects (or is in `side_effects_allowlist`)
4. Check backend is running: `curl http://localhost:8000/api/v1/admin/system/health`

### User Not Found (404)

If tool calls return 404 for user not found:
1. Verify the Open WebUI user has a matching Curatore account with the **same email address**
2. Ensure `ENABLE_FORWARD_USER_INFO_HEADERS=true` is set in Open WebUI
3. Check gateway logs for the forwarded email: `docker logs curatore-mcp 2>&1 | grep "On-Behalf-Of"`

### Connection Refused

**For Docker deployments:**
- Use `host.docker.internal` (same machine) or service name (same network)
- Don't use `localhost` from inside Docker

**Check network:**
```bash
# From Open WebUI container
docker exec -it open-webui curl http://host.docker.internal:8020/health
```

### MCP Protocol Errors

Check the JSON-RPC response for error details:
```bash
curl -X POST http://localhost:8020/mcp \
  -H "Authorization: Bearer YOUR_SERVICE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | jq
```

### Dev Mode

If `MCP_SERVICE_API_KEY` is empty (or not set), the gateway runs in **dev mode** — all requests pass through without authentication. This is useful for local development but should never be used in production.

---

## Architecture

```
Open WebUI
    │
    │  Authorization: Bearer <SERVICE_API_KEY>
    │  X-OpenWebUI-User-Email: alice@company.com
    │
    ├─── MCP Protocol ────► POST /mcp (JSON-RPC)
    │                           │
    └─── OpenAPI ─────────► GET /openapi.json
                            POST /{tool_name}
                                │
                                ▼
                    ┌─────────────────────┐
                    │   MCP Gateway       │
                    │   (port 8020)       │
                    │                     │
                    │  • Policy enforce   │
                    │  • Input validation │
                    │  • Parameter clamps │
                    │  • Identity forward │
                    └──────────┬──────────┘
                               │ X-API-Key: <BACKEND_API_KEY>
                               │ X-On-Behalf-Of: alice@company.com
                               ▼
                    ┌─────────────────────┐
                    │  Curatore Backend   │
                    │   (port 8000)       │
                    │                     │
                    │  Resolves user by   │
                    │  email, scopes to   │
                    │  user's org         │
                    └─────────────────────┘
```

---

## Claude Desktop Integration

Claude Desktop connects via **MCP Streamable HTTP transport** (same as Open WebUI's MCP method). See the [MCP Gateway README](../mcp/README.md#claude-desktop) for configuration.

---

## Related Documentation

- [MCP Gateway README](../mcp/README.md) - Full gateway documentation
- [Auth & Access Model](AUTH_ACCESS_MODEL.md) - Roles, org context, delegated auth
- [CWR Functions & Procedures](FUNCTIONS_PROCEDURES.md) - Function reference
- [Search & Indexing](SEARCH_INDEXING.md) - Search capabilities
- [API Documentation](API_DOCUMENTATION.md) - Backend API reference
