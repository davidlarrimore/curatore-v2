#!/usr/bin/env python3
"""
MCP STDIO Server for Claude Desktop.

This server implements the MCP protocol over STDIO transport.
Claude Desktop launches this as a subprocess and communicates via stdin/stdout.

Usage:
    python stdio_server.py

Environment:
    BACKEND_URL: Curatore backend URL (default: http://backend:8000)
    LOG_LEVEL: Logging level (default: WARNING, use DEBUG for troubleshooting)
"""

import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

import httpx

# Configuration
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "WARNING")

# Configure logging to stderr (stdout is for JSON-RPC)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp.stdio")

# MCP Protocol version
MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "curatore-mcp-stdio"
SERVER_VERSION = "1.0.0"


class MCPStdioServer:
    """MCP server using STDIO transport."""

    def __init__(self):
        self.http_client: Optional[httpx.AsyncClient] = None
        self.tools_cache: Optional[List[Dict[str, Any]]] = None

    async def start(self):
        """Initialize the server."""
        self.http_client = httpx.AsyncClient(
            base_url=BACKEND_URL,
            timeout=60.0,
            follow_redirects=True,
        )
        logger.info(f"MCP STDIO server started, backend: {BACKEND_URL}")

    async def stop(self):
        """Shutdown the server."""
        if self.http_client:
            await self.http_client.aclose()
        logger.info("MCP STDIO server stopped")

    async def handle_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle incoming JSON-RPC message."""
        method = message.get("method", "")
        params = message.get("params", {})
        msg_id = message.get("id")

        logger.debug(f"Received: {method} (id={msg_id})")

        # Notifications (no id) don't need a response
        if msg_id is None:
            logger.debug(f"Notification: {method}")
            return None

        try:
            if method == "initialize":
                result = await self.handle_initialize(params)
            elif method == "tools/list":
                result = await self.handle_tools_list()
            elif method == "tools/call":
                result = await self.handle_tools_call(params)
            elif method == "resources/list":
                result = {"resources": []}
            elif method == "prompts/list":
                result = {"prompts": []}
            else:
                return self._error_response(msg_id, -32601, f"Method not found: {method}")

            return self._success_response(msg_id, result)

        except Exception as e:
            logger.exception(f"Error handling {method}: {e}")
            return self._error_response(msg_id, -32603, f"Internal error: {str(e)}")

    async def handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP initialize request."""
        client_info = params.get("clientInfo", {})
        logger.info(f"Client connected: {client_info.get('name', 'unknown')}")

        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
            "capabilities": {
                "tools": {},
                "resources": {},
                "prompts": {},
            },
        }

    async def handle_tools_list(self) -> Dict[str, Any]:
        """Handle tools/list request."""
        # Fetch tools from backend
        try:
            response = await self.http_client.get("/api/v1/cwr/functions/")
            response.raise_for_status()
            data = response.json()

            tools = []
            for func in data.get("functions", []):
                # Convert to MCP tool format
                tool = {
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "inputSchema": func.get("input_schema", {
                        "type": "object",
                        "properties": {},
                    }),
                }
                tools.append(tool)

            self.tools_cache = tools
            logger.info(f"Loaded {len(tools)} tools from backend")
            return {"tools": tools}

        except httpx.HTTPError as e:
            logger.error(f"Failed to fetch tools: {e}")
            # Return empty list on error
            return {"tools": []}

    async def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            raise ValueError("Missing tool name")

        logger.info(f"Calling tool: {tool_name}")

        try:
            # Execute function via backend
            response = await self.http_client.post(
                f"/api/v1/cwr/functions/{tool_name}/execute/",
                json={"arguments": arguments},
            )
            response.raise_for_status()
            result = response.json()

            # Format as MCP tool result
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(result.get("result", result), indent=2),
                    }
                ],
                "isError": False,
            }

        except httpx.HTTPStatusError as e:
            error_text = e.response.text if e.response else str(e)
            logger.error(f"Tool call failed: {error_text}")
            return {
                "content": [{"type": "text", "text": f"Error: {error_text}"}],
                "isError": True,
            }
        except httpx.HTTPError as e:
            logger.error(f"HTTP error calling tool: {e}")
            return {
                "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                "isError": True,
            }

    def _success_response(self, msg_id: Any, result: Dict[str, Any]) -> Dict[str, Any]:
        """Create JSON-RPC success response."""
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": result,
        }

    def _error_response(self, msg_id: Any, code: int, message: str) -> Dict[str, Any]:
        """Create JSON-RPC error response."""
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }


async def read_message() -> Optional[Dict[str, Any]]:
    """Read a JSON-RPC message from stdin."""
    loop = asyncio.get_event_loop()

    # Read one line at a time
    line = await loop.run_in_executor(None, sys.stdin.readline)
    if not line:
        return None

    line = line.strip()
    if not line:
        return None

    # Claude Desktop sends raw JSON lines
    try:
        return json.loads(line)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse JSON: {e}, line: {line[:100]}")
        return None


def write_message(message: Dict[str, Any]) -> None:
    """Write a JSON-RPC message to stdout."""
    content = json.dumps(message)
    # Claude Desktop expects raw JSON lines, not Content-Length framing
    sys.stdout.write(content + "\n")
    sys.stdout.flush()


async def main():
    """Main event loop."""
    server = MCPStdioServer()

    try:
        await server.start()

        while True:
            try:
                message = await read_message()
                if message is None:
                    # EOF or empty - client disconnected
                    logger.info("Client disconnected (EOF)")
                    break

                response = await server.handle_message(message)
                if response is not None:
                    write_message(response)

            except Exception as e:
                logger.exception(f"Error in message loop: {e}")
                break

    finally:
        await server.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
