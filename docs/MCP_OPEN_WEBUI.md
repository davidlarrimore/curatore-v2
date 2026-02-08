# MCP Gateway & Open WebUI Integration

This guide explains how to integrate Curatore with Open WebUI using the MCP (Model Context Protocol) Gateway.

---

## Overview

The Curatore MCP Gateway exposes CWR functions as MCP-compatible tools, allowing LLMs in Open WebUI to:

- Search documents, SAM.gov notices, forecasts, and Salesforce data
- Retrieve document content
- Summarize, classify, and extract information using LLM functions
- Analyze solicitations and generate classifications

The gateway acts as a stateless proxy, enforcing policies and validating inputs before forwarding requests to the Curatore backend.

---

## Prerequisites

- Curatore v2 running with `docker-compose`
- Open WebUI installed and configured
- An API key for MCP authentication

---

## Quick Start

### 1. Start the MCP Gateway

The MCP Gateway is included in the standard `docker-compose.yml`:

```bash
docker-compose up -d mcp
```

Verify it's running:

```bash
curl http://localhost:8020/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "curatore-mcp",
  "version": "1.0.0"
}
```

### 2. Configure Environment Variables

Set the following in your `.env` file:

```bash
# MCP API Key (used for authentication)
MCP_API_KEY=your_secure_api_key_here

# Default organization ID (optional - uses first org if not set)
DEFAULT_ORG_ID=your-org-uuid-here

# Log level (DEBUG, INFO, WARNING, ERROR)
MCP_LOG_LEVEL=INFO
```

### 3. Configure Open WebUI

In Open WebUI settings, add a new MCP server:

| Field | Value |
|-------|-------|
| Name | Curatore |
| URL | `http://localhost:8020/mcp` |
| API Key | Your `MCP_API_KEY` value |
| Transport | HTTP/SSE |

---

## Available Tools

The MCP Gateway exposes 16 safe functions (no side effects):

### Search Functions

| Tool | Description | Payload |
|------|-------------|---------|
| `search_assets` | Search organization documents | Thin |
| `search_notices` | Search SAM.gov notices | Thin |
| `search_solicitations` | Search SAM.gov solicitations | Thin |
| `search_forecasts` | Search acquisition forecasts | Thin |
| `search_scraped_assets` | Search web-scraped content | Thin |
| `search_salesforce` | Search Salesforce data | Thin |

**Note:** Thin payload means results contain IDs, titles, and scores. Use `get_content` to retrieve full document text.

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

---

## Example Queries

### Search for Documents

```
"Search for documents about cybersecurity published in 2024"
```

The LLM will call `search_assets` with appropriate parameters.

### Summarize a Document

```
"Summarize the document with ID abc-123"
```

The LLM will:
1. Call `get_content` to retrieve the document text
2. Call `llm_summarize` to generate a summary

### Find GSA Solicitations

```
"Find active GSA solicitations for cloud services"
```

The LLM will call `search_solicitations` with filters for agency and keywords.

### Analyze a Solicitation

```
"Analyze solicitation W912HQ-25-R-0001"
```

The LLM will call `analyze_solicitation` to get a structured analysis.

---

## Policy Configuration

The MCP Gateway enforces policies defined in `mcp/policy.yaml`:

### Allowlist

Only functions in the allowlist are exposed. By default, all safe (no side effects) functions are allowed.

### Parameter Clamps

Limits are enforced on parameters to prevent resource abuse:

| Tool | Parameter | Max | Default |
|------|-----------|-----|---------|
| `search_*` | `limit` | 50 | 20 |
| `get_content` | `max_total_chars` | 80,000 | 50,000 |
| `llm_*` | `max_tokens` | 2,000 | 1,000 |

### Facet Validation

When `validate_facets` is enabled, the gateway validates facet filter names against the metadata catalog to prevent hallucinated facet names.

---

## API Reference

### MCP Endpoint

```
POST /mcp
Content-Type: application/json
Authorization: Bearer {MCP_API_KEY}
```

JSON-RPC methods:
- `initialize` - Client handshake
- `tools/list` - List available tools
- `tools/call` - Execute a tool

### REST Endpoints (for testing)

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /mcp/tools` | List tools (REST) |
| `POST /mcp/tools/{name}/call` | Execute tool (REST) |
| `GET /policy` | Get current policy |
| `POST /policy/reload` | Reload policy from file |

---

## Troubleshooting

### Tools Not Appearing in Open WebUI

1. Check MCP Gateway is running: `curl http://localhost:8020/health`
2. Verify API key matches: Check `MCP_API_KEY` in both places
3. Check logs: `docker logs curatore-mcp`

### "Tool not found" Errors

1. Check the tool is in the allowlist in `policy.yaml`
2. Verify the tool doesn't have `side_effects=true`
3. Check the backend is running: `curl http://localhost:8000/api/v1/admin/health`

### "Invalid arguments" Errors

1. Check required parameters are provided
2. Verify parameter types match the schema
3. Check for unknown facet names if using `facet_filters`

### Connection Refused

1. Verify Docker network: MCP container should connect to `backend:8000`
2. Check firewall settings
3. Ensure backend is healthy before MCP starts

---

## Architecture

```
Open WebUI
    ↓ MCP (JSON-RPC over HTTP)
curatore-mcp (port 8020)
    ↓ HTTP (REST API)
curatore-backend (port 8000)
    ↓
PostgreSQL / Redis / MinIO
```

The MCP Gateway:
- Does NOT access the database directly
- Fetches contracts from backend on startup (cached 5 min)
- Validates inputs against JSON Schema from contracts
- Applies policy clamps before forwarding requests
- Returns results in MCP content format

---

## Security Considerations

1. **API Key Authentication**: All MCP requests require a valid API key
2. **Side Effects Blocked**: Functions that modify data are not exposed
3. **Parameter Clamps**: Limits prevent resource abuse
4. **Facet Validation**: Prevents injection of invalid metadata filters
5. **No Direct DB Access**: Gateway only talks to backend over HTTP

For production deployments:
- Use a strong, randomly generated `MCP_API_KEY`
- Consider running behind a reverse proxy with TLS
- Monitor request logs for unusual patterns
- Regularly review and update the policy file

---

## Related Documentation

- [CWR Functions & Procedures](FUNCTIONS_PROCEDURES.md)
- [Search & Indexing](SEARCH_INDEXING.md)
- [API Documentation](API_DOCUMENTATION.md)
- [MCP Requirements](../MCP_REQUIREMENTS.md)
