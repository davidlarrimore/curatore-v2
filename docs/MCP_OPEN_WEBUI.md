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

## Quick Start

### 1. Start the MCP Gateway

```bash
docker-compose up -d mcp
```

Verify it's running:

```bash
curl http://localhost:8020/health
```

### 2. Set Environment Variables

In your `.env` file:

```bash
MCP_API_KEY=your_secure_api_key_here
```

---

## Connection Method 1: MCP Protocol (Streamable HTTP)

Use this method if you want to connect via the native MCP protocol.

### Open WebUI Configuration

1. Go to **Settings** > **Tools** > **MCP Servers**
2. Click **Add MCP Server**
3. Configure:

| Field | Value |
|-------|-------|
| Name | Curatore |
| Type | HTTP (Streamable) |
| URL | See table below |
| Headers | `Authorization: Bearer YOUR_MCP_API_KEY` |

**URL by deployment:**

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
curl -H "Authorization: Bearer YOUR_MCP_API_KEY" \
  http://localhost:8020/rest/tools

# Or use the OpenAI-compatible endpoint
curl -H "Authorization: Bearer YOUR_MCP_API_KEY" \
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
| Token | Your `MCP_API_KEY` value |

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
curl -H "Authorization: Bearer YOUR_MCP_API_KEY" \
  http://localhost:8020/openai/tools | jq '.tools[].function.name'

# Execute a tool
curl -X POST http://localhost:8020/search_assets \
  -H "Authorization: Bearer YOUR_MCP_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"query": "contract management", "limit": 5}'
```

---

## Available Tools

Both connection methods expose the same tools, controlled by `mcp/policy.yaml`:

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

### Allowlist

Only functions in the allowlist are exposed:

```yaml
allowlist:
  - search_assets
  - search_notices
  - prepare_email
  - confirm_email
  # ... etc
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
2. Verify API key is correct
3. Check logs: `docker logs curatore-mcp`

### "Tool not found" Errors

1. Check tool is in `policy.yaml` allowlist
2. Verify tool doesn't have blocked side effects
3. Check backend is running: `curl http://localhost:8000/api/v1/admin/system/health`

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
  -H "Authorization: Bearer YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | jq
```

---

## Architecture

```
Open WebUI
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
                    └──────────┬──────────┘
                               │ HTTP
                               ▼
                    ┌─────────────────────┐
                    │  Curatore Backend   │
                    │   (port 8000)       │
                    └─────────────────────┘
```

---

## Claude Desktop Integration

Claude Desktop uses **STDIO transport** (not HTTP). See the [MCP Gateway README](../mcp/README.md#claude-desktop) for Docker-based setup.

---

## Related Documentation

- [MCP Gateway README](../mcp/README.md) - Full gateway documentation
- [CWR Functions & Procedures](FUNCTIONS_PROCEDURES.md) - Function reference
- [Search & Indexing](SEARCH_INDEXING.md) - Search capabilities
- [API Documentation](API_DOCUMENTATION.md) - Backend API reference
