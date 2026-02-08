# MCP Gateway Main Entry Point
"""FastAPI application with MCP protocol support."""

import logging
import json
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
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
from app.handlers import handle_initialize, handle_tools_list, handle_tools_call
from app.services.policy_service import policy_service
from app.services.backend_client import backend_client

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

            result = await handle_tools_call(
                name=tool_name,
                arguments=arguments,
                org_id=org_id,
                api_key=api_key,
                correlation_id=correlation_id,
            )
            return _json_rpc_response(rpc_request.id, result.model_dump())

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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
