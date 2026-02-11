# Curatore MCP Gateway

A unified tool server that exposes Curatore CWR (Curatore Workflow Runtime) functions to AI assistants via two protocols:

- **MCP (Model Context Protocol)** - For Claude Desktop, Claude Code, and MCP-compatible clients (SDK Streamable HTTP transport)
- **OpenAI Function Calling** - For Open WebUI, ChatGPT, and OpenAI-compatible clients

## Architecture

```
Claude Desktop / Claude Code          Open WebUI / ChatGPT
      │                                      │
      ▼ (Streamable HTTP)                    ▼ (REST/OpenAPI)
┌──────────────────────────────────────────────────────────────┐
│                    MCP HTTP Gateway                           │
│                      (port 8020)                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  /mcp         MCP SDK Streamable HTTP transport        │  │
│  │  /rest/tools  REST convenience endpoints               │  │
│  │  /openai/*    OpenAI-compatible endpoints              │  │
│  │  /openapi.json OpenAPI spec for tool discovery         │  │
│  │  /{tool}      Execute tool (flat path, Open WebUI)     │  │
│  └────────────────────────────────────────────────────────┘  │
│  Policy: auto-derive from exposure_profile,                   │
│          denylist override, clamping, side-effect blocking     │
└──────────────────────────┬───────────────────────────────────┘
                           │ (HTTP)
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                      Curatore Backend                         │
│                        (port 8000)                            │
│                CWR Functions + Tool Contracts                 │
└──────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Start the MCP Gateway

The MCP gateway runs as part of the Curatore stack:

```bash
# From the curatore-v2 root directory
./scripts/dev-up.sh
```

Or start just the MCP service:

```bash
docker-compose up -d mcp
```

### 2. Verify the Gateway

```bash
# Health check
curl http://localhost:8020/health

# Service info
curl http://localhost:8020/
```

### 3. List Available Tools

```bash
# REST format (convenience)
curl -H "Authorization: Bearer mcp_dev_key" \
  http://localhost:8020/rest/tools

# OpenAI format
curl -H "Authorization: Bearer mcp_dev_key" \
  http://localhost:8020/openai/tools
```

---

## Endpoints

### Health & Info

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/health` | GET | No | Health check |
| `/` | GET | No | Service info and available endpoints |

### MCP Protocol (SDK Streamable HTTP)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/mcp` | POST | Yes | MCP SDK Streamable HTTP transport (tools/list, tools/call, resources/list) |

### REST Convenience

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/rest/tools` | GET | Yes | List tools in MCP format |
| `/rest/tools/{name}/call` | POST | Yes | Execute a tool |

### OpenAI Protocol

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/openapi.json` | GET | No | OpenAPI specification for tool discovery |
| `/openai/tools` | GET | Yes | List tools in OpenAI format |
| `/openai/tools/{name}` | POST | Yes | Execute a tool (OpenAI format) |
| `/{tool_name}` | POST | Yes | Execute a tool (flat path for Open WebUI) |

### Progress Streaming (MCP notifications/progress)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/progress` | GET | Yes | List all active progress states |
| `/progress/{token}` | GET | Yes | Get progress state for a token |
| `/progress/{token}/stream` | GET | Yes | SSE stream of progress updates |

### Policy Management

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/policy` | GET | Yes | View current policy configuration |
| `/policy/reload` | POST | Yes | Hot-reload policy from file |

---

## Authentication

All protected endpoints require a Bearer token in the Authorization header:

```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  http://localhost:8020/rest/tools
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_API_KEY` | `mcp_dev_key` | API key for client authentication |
| `DEFAULT_ORG_ID` | (none) | Default organization ID for requests |

---

## Client Configuration

### Claude Desktop

Claude Desktop connects via MCP Streamable HTTP transport:

```json
{
  "mcpServers": {
    "curatore": {
      "type": "http",
      "url": "http://localhost:8020/mcp",
      "headers": {
        "Authorization": "Bearer mcp_dev_key"
      }
    }
  }
}
```

### Claude Code

Configure in your project's `.mcp.json` or global MCP settings:

```json
{
  "servers": {
    "curatore": {
      "type": "http",
      "url": "http://localhost:8020/mcp",
      "headers": {
        "Authorization": "Bearer mcp_dev_key"
      }
    }
  }
}
```

### Open WebUI

1. Go to **Settings** > **Tools** > **OpenAPI Tools**
2. Add a new tool server:
   - **Name**: Curatore
   - **URL**: `http://localhost:8020`
   - **OpenAPI Spec**: `openapi.json`
   - **Authentication**: Bearer Token
   - **Token**: Your MCP API key

Open WebUI will automatically:
- Fetch tools from `GET /openapi.json`
- Execute tools via `POST /{tool_name}` (flat paths)

### ChatGPT / OpenAI-Compatible Clients

For clients that support custom function calling endpoints:

```yaml
Tool Server Configuration:
  Base URL: http://localhost:8020/openai
  List Tools: GET /tools
  Call Tool: POST /tools/{function_name}
  Auth Header: Authorization: Bearer mcp_dev_key
```

### Custom Integration

#### List Tools (OpenAI Format)

```bash
curl -H "Authorization: Bearer mcp_dev_key" \
  http://localhost:8020/openai/tools
```

Response:
```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "search_assets",
        "description": "Search organization documents...",
        "parameters": {
          "type": "object",
          "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "default": 20}
          },
          "required": ["query"]
        },
        "strict": true
      }
    }
  ],
  "total": 15
}
```

#### Execute Tool (OpenAI Format)

```bash
curl -X POST \
  -H "Authorization: Bearer mcp_dev_key" \
  -H "Content-Type: application/json" \
  http://localhost:8020/openai/tools/search_assets \
  -d '{"query": "contract management", "limit": 10}'
```

Response:
```json
{
  "content": [
    {
      "type": "text",
      "text": "[{\"id\": \"asset-123\", \"title\": \"Contract Guide\", \"score\": 0.95}]"
    }
  ],
  "isError": false
}
```

#### Progress Streaming (MCP notifications/progress)

For long-running tool calls, clients can request progress updates using the MCP `_meta.progressToken` pattern:

**1. Call tool with progress token:**
```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  http://localhost:8020/search_assets \
  -d '{
    "_meta": {"progressToken": "my-unique-token"},
    "query": "contract management",
    "limit": 50
  }'
```

**2. Stream progress updates (SSE):**
```bash
curl -N -H "Authorization: Bearer YOUR_API_KEY" \
  http://localhost:8020/progress/my-unique-token/stream
```

**3. Or poll for progress:**
```bash
curl -H "Authorization: Bearer YOUR_API_KEY" \
  http://localhost:8020/progress/my-unique-token
```

---

## Available Tools

Tools are auto-derived from backend contracts. Any function with `exposure_profile.agent=true` is automatically exposed (no policy.yaml edit needed). Use the denylist to block specific functions.

### Search Functions

| Tool | Description | Payload |
|------|-------------|---------|
| `search_assets` | Search organization documents | Thin (IDs, titles, scores) |
| `search_notices` | Search SAM.gov notices | Thin |
| `search_solicitations` | Search SAM.gov solicitations | Thin |
| `search_forecasts` | Search acquisition forecasts | Thin |
| `search_scraped_assets` | Search web-scraped content | Thin |
| `search_salesforce` | Search Salesforce records | Thin |

### Content Retrieval

| Tool | Description | Payload |
|------|-------------|---------|
| `get_asset` | Get full asset details | Full |
| `get_content` | Get document content by IDs | Full |
| `get` | Generic content retrieval | Full |
| `query_model` | Query database models | Full |

### LLM Functions

| Tool | Description | Requires |
|------|-------------|----------|
| `llm_generate` | Generate text with LLM | LLM connection |
| `llm_summarize` | Summarize content | LLM connection |
| `llm_extract` | Extract structured data | LLM connection |
| `llm_classify` | Classify content | LLM connection |

### Compound Functions

| Tool | Description |
|------|-------------|
| `analyze_solicitation` | Full solicitation analysis workflow |
| `classify_document` | Document classification workflow |

### Email Workflow (Two-Step for AI Safety)

| Tool | Description | Side Effects |
|------|-------------|--------------|
| `prepare_email` | Create email preview, returns confirmation token | No |
| `confirm_email` | Send email using confirmation token (15 min expiry) | Yes (allowed via `side_effects_allowlist`) |

The two-step email workflow prevents AI agents from sending emails without explicit human confirmation. The AI calls `prepare_email` to create a preview, shows it to the user, and only calls `confirm_email` after user approval.

---

## Policy Configuration

The gateway enforces security policies defined in `policy.yaml`:

### Auto-Derive Mode (v2.0)

Functions with `exposure_profile.agent=true` in their backend contract are automatically exposed. No allowlist needed — just add the function to the backend and it appears in MCP.

```yaml
version: "2.0"

# Denylist — block specific functions regardless of exposure_profile
denylist: []
```

### Side-Effect Blocking

Functions with `side_effects: true` (e.g., `send_email`, `create_artifact`) are automatically blocked unless explicitly allowed:

```yaml
settings:
  block_side_effects: true
  # Exceptions: allow these side-effect functions
  side_effects_allowlist:
    - confirm_email  # Safe because it requires a token from prepare_email
```

### Parameter Clamping

Limit parameter values to prevent resource abuse:

```yaml
clamps:
  search_assets:
    limit:
      max: 50      # Maximum allowed value
      default: 20  # Default if not specified

  llm_summarize:
    max_tokens:
      max: 2000
      default: 1000
```

### Facet Validation

Validate search facets against the metadata catalog:

```yaml
settings:
  validate_facets: true
```

### Hot-Reload Policy

Update the policy without restarting:

```bash
# Edit policy.yaml, then reload
curl -X POST -H "Authorization: Bearer mcp_dev_key" \
  http://localhost:8020/policy/reload
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND_URL` | `http://backend:8000` | Curatore backend URL |
| `BACKEND_TIMEOUT` | `30` | Backend request timeout (seconds) |
| `MCP_API_KEY` | `mcp_dev_key` | API key for authentication |
| `DEFAULT_ORG_ID` | (none) | Default organization ID |
| `REDIS_URL` | `redis://redis:6379/2` | Redis URL for caching |
| `LOG_LEVEL` | `INFO` | Logging level |
| `DEBUG` | `false` | Debug mode |
| `POLICY_FILE` | `/app/policy.yaml` | Path to policy file |

---

## Response Formats

### Success Response

```json
{
  "content": [
    {
      "type": "text",
      "text": "Result data here..."
    }
  ],
  "isError": false
}
```

### Error Response

```json
{
  "content": [
    {
      "type": "text",
      "text": "Error: Tool 'blocked_function' is not available"
    }
  ],
  "isError": true
}
```

### Tool List (OpenAI Format)

```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "tool_name",
        "description": "Tool description",
        "parameters": { /* JSON Schema */ },
        "strict": true
      }
    }
  ],
  "total": 15
}
```

### Tool List (MCP Format)

```json
{
  "tools": [
    {
      "name": "tool_name",
      "description": "Tool description",
      "inputSchema": { /* JSON Schema */ }
    }
  ]
}
```

---

## Troubleshooting

### Connection Refused

```bash
# Check if the gateway is running
docker ps | grep mcp

# Check logs
docker logs curatore-mcp
```

### 401 Unauthorized

```bash
# Verify your API key
curl -H "Authorization: Bearer YOUR_KEY" \
  http://localhost:8020/rest/tools

# Check configured key
docker exec curatore-mcp env | grep MCP_API_KEY
```

### Tool Not Found

```bash
# List available tools
curl -H "Authorization: Bearer mcp_dev_key" \
  http://localhost:8020/openai/tools | jq '.tools[].function.name'

# Check policy (v2.0 shows denylist)
curl -H "Authorization: Bearer mcp_dev_key" \
  http://localhost:8020/policy | jq '.'
```

### Backend Connection Issues

```bash
# Check backend health
curl http://localhost:8000/api/v1/admin/system/health

# Check gateway logs for backend errors
docker logs curatore-mcp 2>&1 | grep -i error
```

### Reload Policy

```bash
# Edit policy.yaml, then reload
docker exec curatore-mcp cat /app/policy.yaml  # Verify changes
curl -X POST -H "Authorization: Bearer mcp_dev_key" \
  http://localhost:8020/policy/reload
```

---

## Development

### Run Tests

```bash
# Copy tests to container and run
docker cp tests curatore-mcp:/app/tests
docker exec curatore-mcp python -m pytest tests/ -v
```

### View Logs

```bash
docker logs -f curatore-mcp
```

### Local Development

```bash
cd mcp
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8020
```

---

## Security Considerations

1. **API Key Protection**: Store `MCP_API_KEY` securely; rotate regularly in production
2. **Side-Effect Blocking**: Keep `block_side_effects: true` to prevent unintended actions
3. **Parameter Clamping**: Set appropriate limits to prevent resource exhaustion
4. **Network Isolation**: In production, restrict access to trusted networks
5. **Audit Logging**: Monitor logs for unusual activity

---

## Related Documentation

- [CWR Functions & Procedures](../docs/FUNCTIONS_PROCEDURES.md)
- [Tool Contracts](../docs/API_DOCUMENTATION.md#cwr-contracts)
- [Search & Indexing](../docs/SEARCH_INDEXING.md)
- [MCP Protocol Specification](https://modelcontextprotocol.io/)
- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling)
