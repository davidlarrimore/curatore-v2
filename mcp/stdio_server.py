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
                result = await self.handle_resources_list()
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

    async def handle_resources_list(self) -> Dict[str, Any]:
        """Handle resources/list request by calling discover_data_sources."""
        try:
            response = await self.http_client.post(
                "/api/v1/cwr/functions/discover_data_sources/execute",
                json={"params": {}},
            )
            response.raise_for_status()
            result = response.json()

            # Convert to MCP resources format
            data = result.get("data") or result.get("result", {}).get("data", {})
            resources = []

            for source_type in data.get("source_types", []):
                st_key = source_type.get("type", "unknown")
                display_name = source_type.get("display_name", st_key)
                description = source_type.get("description", "")
                capabilities = source_type.get("capabilities", [])
                instances = source_type.get("instances", [])

                # Build description
                desc_parts = [description.strip()] if description else []
                if capabilities:
                    desc_parts.append("Capabilities: " + "; ".join(capabilities[:3]))
                if instances:
                    names = [i.get("name", "") for i in instances[:5] if i.get("name")]
                    if names:
                        desc_parts.append(f"Configured: {', '.join(names)}")

                resources.append({
                    "uri": f"curatore://data-sources/{st_key}",
                    "name": display_name,
                    "description": " | ".join(desc_parts),
                    "mimeType": "text/plain",
                })

            logger.info(f"Loaded {len(resources)} resources")
            return {"resources": resources}

        except Exception as e:
            logger.warning(f"Failed to fetch resources: {e}")
            return {"resources": []}

    async def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if not tool_name:
            raise ValueError("Missing tool name")

        logger.info(f"Calling tool: {tool_name}")

        try:
            # Execute function via backend
            # Note: Backend expects {"params": {...}}, not {"arguments": {...}}
            response = await self.http_client.post(
                f"/api/v1/cwr/functions/{tool_name}/execute/",
                json={"params": arguments},
            )
            response.raise_for_status()
            result = response.json()

            # Format as MCP tool result with readable text
            text = _format_function_result(result)
            return {
                "content": [{"type": "text", "text": text}],
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


def _format_function_result(result: Dict[str, Any]) -> str:
    """
    Format a backend function result as readable text for LLM consumption.

    Shared formatting logic for the STDIO server. Produces clean markdown
    instead of raw JSON dumps.
    """
    status = result.get("status", "unknown")
    if status in ("error", "failed") or result.get("error"):
        error_msg = result.get("error") or result.get("message") or "Unknown error"
        return f"Error: {error_msg}"

    data = result.get("data")
    message = result.get("message", "")
    metadata = result.get("metadata", {})
    items_processed = result.get("items_processed", 0)

    parts: List[str] = []

    if message:
        parts.append(message)

    if data is None:
        if not message:
            parts.append("Operation completed successfully.")
    elif isinstance(data, str):
        parts.append(data)
    elif isinstance(data, list):
        if len(data) == 0:
            if not message:
                parts.append("No results found.")
        elif data and isinstance(data[0], dict) and "id" in data[0] and ("title" in data[0] or "display_type" in data[0] or "name" in data[0]):
            # Dict list with identifiable items — format as readable markdown
            for i, item in enumerate(data, 1):
                title = item.get("title") or item.get("name") or "Untitled"
                display_type = item.get("display_type") or item.get("type") or item.get("source_type") or "Item"
                item_id = item.get("id", "")
                fields = item.get("fields") or {}
                meta = item.get("metadata") or {}

                parts.append(f"### {i}. {title}")
                parts.append(f"Type: {display_type} | ID: {item_id}")

                detail_parts = []
                score = meta.get("score") or item.get("score")
                if score is not None:
                    try:
                        detail_parts.append(f"Score: {float(score):.2f}")
                    except (ValueError, TypeError):
                        pass
                for key in ("source_type", "site_name", "content_type", "original_filename",
                            "folder_path", "source_url", "url", "created_at",
                            "detail_url", "fiscal_year", "agency_name", "naics_code",
                            "stage_name", "amount", "probability", "close_date",
                            "opportunity_type", "role", "lead_source", "fiscal_quarter",
                            "account_type", "industry", "department", "description",
                            "email", "phone", "website", "custom_dates",
                            "notice_type", "set_aside_code", "response_deadline",
                            "posted_date", "bureau_name"):
                    val = fields.get(key) or item.get(key)
                    if val and key not in ("type", "id", "title", "score", "display_type", "name"):
                        val_str = str(val)
                        if len(val_str) > 200:
                            val_str = val_str[:200] + "..."
                        detail_parts.append(f"{key.replace('_', ' ').title()}: {val_str}")
                if detail_parts:
                    parts.append(" | ".join(detail_parts))

                snippet = meta.get("snippet") or meta.get("highlights") or item.get("highlights")
                if snippet:
                    if isinstance(snippet, dict):
                        content_highlights = snippet.get("content", [])
                        snippet = content_highlights[0] if content_highlights else str(snippet)
                    if isinstance(snippet, list):
                        snippet = " ... ".join(str(s) for s in snippet[:3])
                    parts.append(f"> {str(snippet)[:500].replace('<mark>', '**').replace('</mark>', '**')}")

                text_content = item.get("text") or item.get("content")
                if text_content and isinstance(text_content, str):
                    if len(text_content) > 4000:
                        parts.append(text_content[:4000] + "\n... (truncated)")
                    else:
                        parts.append(text_content)

                parts.append("")
        else:
            parts.append(json.dumps(data, indent=2, default=str))
    elif isinstance(data, dict):
        parts.append(json.dumps(data, indent=2, default=str))
    else:
        parts.append(str(data))

    # Clean metadata (omit nulls)
    clean_meta: Dict[str, Any] = {}
    for k, v in metadata.items():
        if k == "result_type" or v is None:
            continue
        if isinstance(v, dict):
            v = {nk: nv for nk, nv in v.items() if nv is not None}
            if not v:
                continue
        clean_meta[k] = v
    if items_processed:
        clean_meta["items_processed"] = items_processed

    if clean_meta:
        meta_lines = ["---"]
        for k, v in clean_meta.items():
            label = k.replace("_", " ").title()
            if isinstance(v, dict):
                nested = ", ".join(f"{nk}={nv}" for nk, nv in v.items())
                meta_lines.append(f"{label}: {nested}")
            elif isinstance(v, list):
                meta_lines.append(f"{label}: {', '.join(str(x) for x in v)}")
            else:
                meta_lines.append(f"{label}: {v}")
        parts.append("\n".join(meta_lines))

    return "\n\n".join(parts)


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
