# MCP Gateway Configuration
"""Configuration settings loaded from environment variables."""

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """MCP Gateway settings from environment variables."""

    # Backend connection
    backend_url: str = Field(
        default="http://backend:8000",
        description="Curatore backend URL",
    )
    backend_timeout: int = Field(
        default=30,
        description="Backend request timeout in seconds",
    )

    # Authentication
    mcp_api_key: str = Field(
        default="mcp_dev_key",
        description="API key for MCP client authentication",
    )
    default_org_id: Optional[str] = Field(
        default=None,
        description="Default organization ID for authenticated requests",
    )

    # Redis for caching
    redis_url: str = Field(
        default="redis://redis:6379/2",
        description="Redis URL for caching",
    )

    # Server settings
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8020, description="Server port")
    log_level: str = Field(default="INFO", description="Logging level")
    debug: bool = Field(default=False, description="Debug mode")

    # SSL settings (optional)
    ssl_keyfile: Optional[str] = Field(default=None, description="Path to SSL private key")
    ssl_certfile: Optional[str] = Field(default=None, description="Path to SSL certificate")

    # Policy file
    policy_file: str = Field(
        default="/app/policy.yaml",
        description="Path to policy configuration file",
    )

    # MCP protocol settings
    mcp_protocol_version: str = Field(
        default="2025-06-18",
        description="MCP protocol version",
    )
    mcp_server_name: str = Field(
        default="curatore-mcp",
        description="MCP server name",
    )
    mcp_server_version: str = Field(
        default="1.0.0",
        description="MCP server version",
    )

    class Config:
        env_prefix = ""
        case_sensitive = False
        env_file = ".env"
        env_file_encoding = "utf-8"


# Global settings instance
settings = Settings()
