# MCP Gateway Main Entry Point
"""FastAPI application with MCP protocol support."""

import logging
import json
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.middleware.auth import AuthMiddleware
from app.middleware.correlation import CorrelationMiddleware
from app.models.mcp import (
    JSONRPCRequest,
    JSONRPCResponse,
    MCPInitializeResponse,
    MCPToolsListResponse,
    MCPToolsCallResponse,
)
from app.models.openai import OpenAIToolsResponse
from app.handlers import handle_initialize, handle_tools_list, handle_tools_call, extract_progress_token, handle_resources_list
from app.services.openai_converter import mcp_tools_to_openai
from app.services.policy_service import policy_service
from app.services.backend_client import backend_client
from app.services.progress_service import progress_service

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("mcp.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info(f"Starting MCP Gateway v{settings.mcp_server_version}")
    policy_service.load()
    logger.info(f"Loaded policy with {len(policy_service.allowlist)} allowed tools")
    yield
    # Shutdown
    logger.info("Shutting down MCP Gateway")
    await backend_client.close()


app = FastAPI(
    title="Curatore MCP Gateway",
    description="MCP-compatible gateway for Curatore CWR functions",
    version=settings.mcp_server_version,
    lifespan=lifespan,
    openapi_url=None,  # Disable built-in OpenAPI, we generate our own
    docs_url=None,     # Disable Swagger UI
    redoc_url=None,    # Disable ReDoc
)

# Add middleware (order matters - first added = outermost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(CorrelationMiddleware)
app.add_middleware(AuthMiddleware)


# =============================================================================
# Health Endpoints
# =============================================================================


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": settings.mcp_server_name,
        "version": settings.mcp_server_version,
    }


@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": settings.mcp_server_name,
        "version": settings.mcp_server_version,
        "protocol": settings.mcp_protocol_version,
        "endpoints": {
            "health": "/health",
            "mcp": "/mcp",
            "openai": "/openai/tools",
        },
    }


# =============================================================================
# MCP Protocol Endpoint
# =============================================================================


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    """
    MCP JSON-RPC endpoint.

    Handles MCP protocol messages:
    - initialize: Client handshake
    - tools/list: List available tools
    - tools/call: Execute a tool
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": -32700, "message": "Parse error"}},
        )

    # Parse JSON-RPC request
    try:
        rpc_request = JSONRPCRequest(**body)
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": -32600, "message": f"Invalid Request: {e}"}},
        )

    # Get request context
    org_id = getattr(request.state, "org_id", None)
    api_key = getattr(request.state, "api_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)

    # Route to appropriate handler
    method = rpc_request.method
    params = rpc_request.params or {}

    try:
        if method == "initialize":
            result = await handle_initialize(params)
            return _json_rpc_response(rpc_request.id, result.model_dump())

        elif method == "tools/list":
            result = await handle_tools_list(api_key, correlation_id)
            return _json_rpc_response(rpc_request.id, result.model_dump())

        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if not tool_name:
                return _json_rpc_error(rpc_request.id, -32602, "Missing tool name")

            # Extract MCP progress token from _meta
            progress_token, clean_arguments = extract_progress_token(arguments)

            result = await handle_tools_call(
                name=tool_name,
                arguments=clean_arguments,
                org_id=org_id,
                api_key=api_key,
                correlation_id=correlation_id,
                progress_token=progress_token,
            )
            return _json_rpc_response(rpc_request.id, result.model_dump())

        elif method == "resources/list":
            result = await handle_resources_list(api_key, correlation_id)
            return _json_rpc_response(rpc_request.id, result)

        else:
            return _json_rpc_error(rpc_request.id, -32601, f"Method not found: {method}")

    except Exception as e:
        logger.exception(f"Error handling {method}: {e}")
        return _json_rpc_error(rpc_request.id, -32603, f"Internal error: {str(e)}")


def _json_rpc_response(id: Any, result: Dict[str, Any]) -> JSONResponse:
    """Create JSON-RPC success response."""
    return JSONResponse(
        content={
            "jsonrpc": "2.0",
            "id": id,
            "result": result,
        }
    )


def _json_rpc_error(id: Any, code: int, message: str) -> JSONResponse:
    """Create JSON-RPC error response."""
    return JSONResponse(
        content={
            "jsonrpc": "2.0",
            "id": id,
            "error": {"code": code, "message": message},
        }
    )


# =============================================================================
# Direct REST Endpoints (for easier testing)
# =============================================================================


@app.get("/mcp/tools")
async def list_tools(request: Request):
    """List available MCP tools (REST endpoint for testing)."""
    api_key = getattr(request.state, "api_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)

    result = await handle_tools_list(api_key, correlation_id)
    return result.model_dump()


@app.post("/mcp/tools/{name}/call")
async def call_tool(name: str, request: Request):
    """Execute an MCP tool (REST endpoint for testing)."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}

    org_id = getattr(request.state, "org_id", None)
    api_key = getattr(request.state, "api_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)

    result = await handle_tools_call(
        name=name,
        arguments=body.get("arguments", {}),
        org_id=org_id,
        api_key=api_key,
        correlation_id=correlation_id,
    )
    return result.model_dump()


# =============================================================================
# Policy Management Endpoints
# =============================================================================


@app.get("/policy")
async def get_policy():
    """Get current policy configuration."""
    policy = policy_service.policy
    return {
        "version": policy.version,
        "allowlist": policy.allowlist,
        "settings": policy.settings.model_dump(),
    }


@app.post("/policy/reload")
async def reload_policy():
    """Reload policy from file."""
    policy = policy_service.reload()
    logger.info(f"Reloaded policy with {len(policy.allowlist)} allowed tools")
    return {
        "status": "reloaded",
        "allowlist_count": len(policy.allowlist),
    }


# =============================================================================
# Progress Streaming Endpoints (MCP notifications/progress)
# =============================================================================


@app.get("/progress/{token}")
async def get_progress(token: str):
    """
    Get current progress state for a token.

    Returns the current state without streaming.
    """
    state = progress_service.get(token)
    if not state:
        return JSONResponse(
            status_code=404,
            content={"error": "Progress token not found"},
        )
    return state.to_dict()


@app.get("/progress/{token}/stream")
async def stream_progress(token: str, request: Request):
    """
    Stream progress updates via Server-Sent Events (SSE).

    This implements MCP's notifications/progress pattern over HTTP.
    Connect to this endpoint before or immediately after starting a tool
    call with a progressToken to receive real-time updates.

    Events:
    - `progress`: Progress update with current state
    - `complete`: Tool execution completed
    - `error`: Tool execution failed

    Example:
        ```javascript
        const eventSource = new EventSource('/progress/my-token/stream');
        eventSource.onmessage = (e) => console.log(JSON.parse(e.data));
        ```
    """
    state = progress_service.get(token)
    if not state:
        return JSONResponse(
            status_code=404,
            content={"error": "Progress token not found"},
        )

    async def event_generator():
        """Generate SSE events from progress updates."""
        async for notification in progress_service.subscribe(token):
            # Format as SSE
            params = notification.get("params", {})
            status = params.get("status", "progress")

            event_type = "progress"
            if status == "completed":
                event_type = "complete"
            elif status == "error":
                event_type = "error"

            yield f"event: {event_type}\n"
            yield f"data: {json.dumps(notification)}\n\n"

            # End stream on completion or error
            if status in ("completed", "error"):
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/progress")
async def list_active_progress():
    """List all active progress states."""
    return progress_service.list_active()


# =============================================================================
# OpenAI-Compatible Endpoints
# =============================================================================


@app.get("/openai/tools", response_model=OpenAIToolsResponse)
async def list_openai_tools(request: Request):
    """
    List available tools in OpenAI function calling format.

    This endpoint provides tools in the format expected by OpenAI-compatible
    clients like Open WebUI and ChatGPT. Tools are filtered by the same
    policy as MCP (allowlist, side-effect blocking).
    """
    api_key = getattr(request.state, "api_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)

    # Reuse existing MCP tools list handler
    mcp_result = await handle_tools_list(api_key, correlation_id)

    # Convert to OpenAI format
    openai_tools = mcp_tools_to_openai(mcp_result.tools)

    return OpenAIToolsResponse(
        tools=openai_tools,
        total=len(openai_tools),
    )


@app.post("/openai/tools/{name}")
async def call_openai_tool(name: str, request: Request):
    """
    Execute a tool using OpenAI-compatible format.

    OpenAI clients send arguments directly in the request body (not wrapped
    in an "arguments" key like MCP). This endpoint handles both formats
    for compatibility.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}

    org_id = getattr(request.state, "org_id", None)
    api_key = getattr(request.state, "api_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)

    # OpenAI sends args directly; MCP wraps in "arguments"
    # Support both formats for maximum compatibility
    if "arguments" in body and isinstance(body["arguments"], dict):
        arguments = body["arguments"]
    else:
        arguments = body

    # Reuse existing MCP tool call handler
    result = await handle_tools_call(
        name=name,
        arguments=arguments,
        org_id=org_id,
        api_key=api_key,
        correlation_id=correlation_id,
    )
    return result.model_dump()


@app.get("/openapi.json")
async def get_openapi_spec(request: Request):
    """
    Generate OpenAPI specification for Open WebUI integration.

    This dynamically generates an OpenAPI 3.1 spec based on the available
    tools, allowing Open WebUI to discover and call tools as API endpoints.
    """
    api_key = getattr(request.state, "api_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)

    # Get available tools
    mcp_result = await handle_tools_list(api_key, correlation_id)
    openai_tools = mcp_tools_to_openai(mcp_result.tools)

    # Build OpenAPI paths from tools - flat paths like Open WebUI expects
    paths = {}
    for tool in openai_tools:
        func = tool.function
        tool_name = func.name

        # Create POST endpoint for each tool at root level
        paths[f"/{tool_name}"] = {
            "post": {
                "operationId": tool_name,
                "summary": func.description.split("\n")[0],  # First line
                "description": func.description,
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": func.parameters
                        }
                    }
                },
                "responses": {
                    "200": {
                        "description": "Successful response",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "content": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "type": {"type": "string"},
                                                    "text": {"type": "string"}
                                                }
                                            }
                                        },
                                        "isError": {"type": "boolean"}
                                    }
                                }
                            }
                        }
                    }
                },
                "security": [{"BearerAuth": []}]
            }
        }

    # Build complete OpenAPI spec
    openapi_spec = {
        "openapi": "3.1.0",
        "info": {
            "title": "Curatore CWR Tools",
            "description": "Curatore Workflow Runtime tools for document search, content retrieval, and LLM operations.",
            "version": settings.mcp_server_version,
        },
        "servers": [
            {
                "url": "",
                "description": "Curatore MCP Gateway"
            }
        ],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "API key authentication"
                }
            }
        },
        "security": [{"BearerAuth": []}]
    }

    return openapi_spec


@app.post("/{tool_name}")
async def call_tool_direct(tool_name: str, request: Request):
    """
    Execute a tool directly (Open WebUI compatible flat path).
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}

    org_id = getattr(request.state, "org_id", None)
    api_key = getattr(request.state, "api_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)

    # Support both direct args and wrapped args
    if "arguments" in body and isinstance(body["arguments"], dict):
        arguments = body["arguments"]
    else:
        arguments = body

    result = await handle_tools_call(
        name=tool_name,
        arguments=arguments,
        org_id=org_id,
        api_key=api_key,
        correlation_id=correlation_id,
    )
    return result.model_dump()


if __name__ == "__main__":
    import uvicorn

    # Build uvicorn config
    config = {
        "app": "app.main:app",
        "host": settings.host,
        "port": settings.port,
        "reload": settings.debug,
    }

    # Add SSL if configured
    if settings.ssl_certfile and settings.ssl_keyfile:
        config["ssl_certfile"] = settings.ssl_certfile
        config["ssl_keyfile"] = settings.ssl_keyfile
        logger.info(f"Starting with HTTPS on port {settings.port}")
    else:
        logger.info(f"Starting with HTTP on port {settings.port}")

    uvicorn.run(**config)
