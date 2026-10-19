from typing import Final


MCP_SERVER_NAME: Final[str] = "libre-box"
MCP_SERVER_VERSION: Final[str] = "1.0.0"
MCP_PORT: Final[int] = 8080
MCP_ALLOWED_HOSTS: Final[tuple[str, ...]] = ("mcp:*", "localhost:*", "127.0.0.1:*")
MCP_MAX_REQUEST_BODY_BYTES: Final[int] = 16 * 1024 * 1024
MCP_MAX_CONCURRENT_REQUESTS: Final[int] = 64
MCP_GRACEFUL_SHUTDOWN_SECONDS: Final[int] = 10
MCP_HEALTH_TIMEOUT_SECONDS: Final[float] = 2.0

AUDIT_VALUE_PREVIEW_CHARS: Final[int] = 200
AUDIT_ARGUMENTS_MAX_CHARS: Final[int] = 2000
AUDIT_SECRET_ARGUMENTS: Final[frozenset[str]] = frozenset({"env"})
AUDIT_REDACTED_TOOL_ARGUMENTS: Final[dict[str, frozenset[str]]] = {
    "file_write": frozenset({"content"}),
    "file_edit": frozenset({"old_string", "new_string"}),
}

TOOL_ENCODING_MAX_CHARS: Final[int] = 64
TOOL_TIMEZONE_MAX_CHARS: Final[int] = 64

SANDBOX_INVENTORY_PATH: Final[str] = "/usr/local/share/libre-box/inventory.json"
SANDBOX_INVENTORY_MAX_CHARS: Final[int] = 8 * 1024 * 1024
SANDBOX_INVENTORY_TIMEOUT_SECONDS: Final[int] = 15
