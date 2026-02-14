# MCP Gateway Main Entry Point
"""FastAPI application with MCP SDK Streamable HTTP transport."""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from app.config import settings
from app.handlers import handle_tools_call, handle_tools_list
from app.middleware.auth import AuthMiddleware
from app.middleware.correlation import CorrelationMiddleware
from app.models.openai import OpenAIToolsResponse
from app.server import ctx_api_key, ctx_correlation_id, ctx_user_email, session_manager
from app.services.backend_client import backend_client
from app.services.openai_converter import mcp_tools_to_openai
from app.services.policy_service import policy_service
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

    policy = policy_service.policy
    if policy.is_v2:
        logger.info(f"Policy v{policy.version}: auto-derive mode, {len(policy.denylist)} denied tools")
    else:
        logger.info(f"Policy v{policy.version}: legacy mode, {len(policy.allowlist)} allowed tools")

    # Start MCP SDK session manager (manages Streamable HTTP transport lifecycle)
    async with session_manager.run():
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
# MCP SDK Streamable HTTP Transport at /mcp
# =============================================================================


class MCPTransport:
    """
    ASGI app that propagates auth headers into contextvars, then delegates
    to the MCP SDK session manager. Used as both a Route endpoint (bare
    /mcp) and a Mount sub-app (/mcp/*).

    Starlette's Route treats class instances (non-function callables) as
    raw ASGI apps, passing (scope, receive, send) directly.
    """

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            # Use the backend API key (ServiceAccount key), not the incoming Bearer token
            ctx_api_key.set(settings.backend_api_key or None)
            # Extract user email forwarded by Open WebUI
            ctx_user_email.set(
                headers.get(b"x-openwebui-user-email", b"").decode() or None
            )
            ctx_correlation_id.set(
                headers.get(b"x-correlation-id", b"").decode() or None
            )
        await session_manager.handle_request(scope, receive, send)


_mcp_transport = MCPTransport()

# Register as a Starlette Route for the bare /mcp path (POST for JSON-RPC,
# GET for SSE streaming, DELETE for session termination).
# Inserted at position 0 so it takes precedence over the catch-all
# /{tool_name} route which would otherwise intercept POST /mcp.
# Note: Starlette's Mount only matches /mcp/ (with trailing slash) and
# /mcp/*, not the bare /mcp path that MCP clients POST to.
app.router.routes.insert(0, Route("/mcp", _mcp_transport, methods=["GET", "POST", "DELETE"]))


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
            "rest": "/rest/tools",
        },
    }


# =============================================================================
# REST Convenience Endpoints (relocated from /mcp/tools to /rest/tools)
# =============================================================================


@app.get("/rest/tools")
async def list_tools(request: Request):
    """List available MCP tools (REST endpoint for testing)."""
    api_key = getattr(request.state, "api_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)
    user_email = getattr(request.state, "user_email", None)

    result = await handle_tools_list(api_key, correlation_id, user_email=user_email)
    return result.model_dump()


@app.post("/rest/tools/{name}/call")
async def call_tool(name: str, request: Request):
    """Execute an MCP tool (REST endpoint for testing)."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        body = {}

    api_key = getattr(request.state, "api_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)
    user_email = getattr(request.state, "user_email", None)

    result = await handle_tools_call(
        name=name,
        arguments=body.get("arguments", {}),
        api_key=api_key,
        correlation_id=correlation_id,
        user_email=user_email,
    )
    return result.model_dump()


# =============================================================================
# Policy Management Endpoints
# =============================================================================


@app.get("/policy")
async def get_policy():
    """Get current policy configuration."""
    policy = policy_service.policy
    result = {
        "version": policy.version,
        "settings": policy.settings.model_dump(),
    }
    if policy.is_v2:
        result["denylist"] = policy.denylist
    else:
        result["allowlist"] = policy.allowlist
    return result


@app.post("/policy/reload")
async def reload_policy():
    """Reload policy from file."""
    policy = policy_service.reload()
    if policy.is_v2:
        logger.info(f"Reloaded policy v{policy.version}: {len(policy.denylist)} denied tools")
        return {
            "status": "reloaded",
            "version": policy.version,
            "denylist_count": len(policy.denylist),
        }
    else:
        logger.info(f"Reloaded policy v{policy.version}: {len(policy.allowlist)} allowed tools")
        return {
            "status": "reloaded",
            "version": policy.version,
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
    policy as MCP (auto-derive + side-effect blocking).
    """
    api_key = getattr(request.state, "api_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)
    user_email = getattr(request.state, "user_email", None)

    # Reuse existing MCP tools list handler
    mcp_result = await handle_tools_list(api_key, correlation_id, user_email=user_email)

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

    api_key = getattr(request.state, "api_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)
    user_email = getattr(request.state, "user_email", None)

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
        api_key=api_key,
        correlation_id=correlation_id,
        user_email=user_email,
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
    user_email = getattr(request.state, "user_email", None)

    # Get available tools
    mcp_result = await handle_tools_list(api_key, correlation_id, user_email=user_email)
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

    api_key = getattr(request.state, "api_key", None)
    correlation_id = getattr(request.state, "correlation_id", None)
    user_email = getattr(request.state, "user_email", None)

    # Support both direct args and wrapped args
    if "arguments" in body and isinstance(body["arguments"], dict):
        arguments = body["arguments"]
    else:
        arguments = body

    result = await handle_tools_call(
        name=tool_name,
        arguments=arguments,
        api_key=api_key,
        correlation_id=correlation_id,
        user_email=user_email,
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
