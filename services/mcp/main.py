import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable

import uvloop
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from config.constants import DEFAULT_COMMAND_TIMEOUT_SECONDS, OUTPUT_CHAR_LIMIT_DEFAULT, SANDBOX_CONTAINER_NAME
from config.settings import AppSettings, load_app_settings
from domain.exceptions import SandboxError
from infrastructure.docker.sandbox_client import SandboxClient
from infrastructure.http.server import build_server, install_shutdown_handlers, serve
from mcp_server.audit import ToolCallAuditMiddleware
from mcp_server.constants import MCP_ALLOWED_HOSTS, MCP_GRACEFUL_SHUTDOWN_SECONDS, MCP_HEALTH_TIMEOUT_SECONDS, MCP_MAX_CONCURRENT_REQUESTS, MCP_MAX_REQUEST_BODY_BYTES, MCP_PORT, MCP_SERVER_NAME, MCP_SERVER_VERSION
from mcp_server.descriptions import build_server_instructions
from mcp_server.tools.background_tools import register_background_tools
from mcp_server.tools.file_tools import register_file_tools
from mcp_server.tools.shell_tools import register_shell_tools
from mcp_server.tools.system_tools import register_system_tools
from services.background_constants import BACKGROUND_LOG_DIR
from services.background_service import BackgroundService
from services.file_service import FileService
from services.image_view_service import ImageViewService
from utils.logger import configure_logging, logger


def _create_healthz(sandbox_client: SandboxClient) -> Callable[[Request], Awaitable[JSONResponse]]:
    async def healthz(request: Request) -> JSONResponse:
        try:
            async with asyncio.timeout(MCP_HEALTH_TIMEOUT_SECONDS):
                await sandbox_client.generation()
        except (SandboxError, TimeoutError) as error:
            logger.warning(f"MCP health probe failed: {error}")
            return JSONResponse({"status": "unavailable", "dependency": "sandbox"}, status_code=503, headers={"Retry-After": "5"})

        return JSONResponse({"status": "ok"})

    return healthz


def create_mcp_server(sandbox_client: SandboxClient, default_timeout: int = DEFAULT_COMMAND_TIMEOUT_SECONDS, output_char_limit: int = OUTPUT_CHAR_LIMIT_DEFAULT, egress_allow_cidrs: str = "", egress_block_cidrs: str = "") -> MCPServer:
    mcp = MCPServer(MCP_SERVER_NAME, version=MCP_SERVER_VERSION, instructions=build_server_instructions(egress_allow_cidrs, egress_block_cidrs), middleware=[ToolCallAuditMiddleware()])
    register_background_tools(mcp, BackgroundService(sandbox_client, BACKGROUND_LOG_DIR, output_char_limit), default_timeout, output_char_limit)
    register_file_tools(mcp, FileService(), ImageViewService())
    register_shell_tools(mcp, sandbox_client, default_timeout, output_char_limit)
    register_system_tools(mcp, sandbox_client, default_timeout)
    return mcp


def _create_mcp_application(sandbox_client: SandboxClient, settings: AppSettings) -> Starlette:
    mcp = create_mcp_server(sandbox_client, settings.default_command_timeout_seconds, settings.output_char_limit, settings.egress_allow_cidrs, settings.egress_block_cidrs)
    transport_security = TransportSecuritySettings(allowed_hosts=list(MCP_ALLOWED_HOSTS), allowed_origins=["*"])
    mcp_http_application = mcp.streamable_http_app(transport_security=transport_security, json_response=True, stateless_http=True, max_request_body_size=MCP_MAX_REQUEST_BODY_BYTES)

    @contextlib.asynccontextmanager
    async def _run_session_manager(_: Starlette) -> AsyncIterator[None]:
        async with mcp.session_manager.run():
            yield

    return Starlette(
        routes=[
            Route("/healthz", _create_healthz(sandbox_client), methods=["GET"]),
            Mount("/", app=mcp_http_application),
        ],
        lifespan=_run_session_manager,
    )


async def main() -> None:
    settings = load_app_settings()
    configure_logging(settings.log_level, settings.log_serialize)
    logger.info("MCP server setup started")

    sandbox_client = SandboxClient(SANDBOX_CONTAINER_NAME, settings.output_char_limit)
    try:
        await sandbox_client.start()
        server = build_server(_create_mcp_application(sandbox_client, settings), MCP_PORT, MCP_MAX_CONCURRENT_REQUESTS, MCP_GRACEFUL_SHUTDOWN_SECONDS)
        install_shutdown_handlers(lambda: setattr(server, "should_exit", True))

        logger.info(f"MCP server listening port={MCP_PORT}")
        await serve(server)
    except Exception as error:
        logger.exception(f"Fatal error during MCP service execution: {error}")
        raise
    finally:
        await sandbox_client.close()
        logger.info("MCP server shutdown completed")


if __name__ == "__main__":
    try:
        uvloop.run(main())
    except KeyboardInterrupt:
        logger.info("MCP server interrupted by user")
