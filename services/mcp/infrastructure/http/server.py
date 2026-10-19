import asyncio
import contextlib
import signal
from collections.abc import Callable

import uvicorn
from starlette.types import ASGIApp

from infrastructure.http.request_context import RequestContextMiddleware
from utils.logger import logger


class ServerStartupError(RuntimeError):
    def __init__(self, port: int, exit_code: object) -> None:
        super().__init__(f"Uvicorn server on port {port} exited during startup with code {exit_code}. The cause is logged above, typically the port is already in use")


def build_server(application: ASGIApp, port: int, max_concurrent_requests: int, graceful_shutdown_seconds: int) -> uvicorn.Server:
    server_config = uvicorn.Config(app=RequestContextMiddleware(application), host="0.0.0.0", port=port, log_config=None, access_log=False, loop="asyncio", limit_concurrency=max_concurrent_requests, timeout_graceful_shutdown=graceful_shutdown_seconds)
    server = uvicorn.Server(server_config)

    logger.info(f"Configured uvicorn server port={port} limit_concurrency={max_concurrent_requests} timeout_graceful_shutdown={graceful_shutdown_seconds}")
    return server


def install_shutdown_handlers(on_shutdown: Callable[[], None]) -> None:
    running_loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            running_loop.add_signal_handler(shutdown_signal, on_shutdown)


async def serve(server: uvicorn.Server) -> None:
    try:
        await server.serve()
    except SystemExit as error:
        raise ServerStartupError(server.config.port, error.code) from error
