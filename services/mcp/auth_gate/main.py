import uvloop

from auth_gate.app import AuthGate, create_auth_app
from auth_gate.constants import AUTH_GRACEFUL_SHUTDOWN_SECONDS, AUTH_LOG_FILE_NAME, AUTH_MAX_CONCURRENT_REQUESTS, AUTH_PORT, LIBRECHAT_DATABASE_NAME
from auth_gate.session_store import SessionStore
from config.settings import load_auth_gate_settings
from infrastructure.http.server import ServerStartupError, build_server, install_shutdown_handlers, serve
from utils.logger import configure_logging, logger


async def main() -> None:
    settings = load_auth_gate_settings()
    configure_logging(settings.log_level, settings.log_serialize, AUTH_LOG_FILE_NAME)
    logger.info("Auth gate setup started")

    session_store = SessionStore(settings.mongo_uri.get_secret_value(), LIBRECHAT_DATABASE_NAME)
    auth_gate = AuthGate(session_store, settings.jwt_refresh_secret.get_secret_value())

    server = build_server(create_auth_app(auth_gate), AUTH_PORT, AUTH_MAX_CONCURRENT_REQUESTS, AUTH_GRACEFUL_SHUTDOWN_SECONDS)
    install_shutdown_handlers(lambda: setattr(server, "should_exit", True))

    logger.info(f"Auth gate listening port={AUTH_PORT}")
    try:
        await serve(server)
    except ServerStartupError as error:
        logger.exception(f"Auth gate failed to start: {error}")
        raise
    finally:
        await session_store.close()
        logger.info("Auth gate shutdown completed")


if __name__ == "__main__":
    try:
        uvloop.run(main())
    except KeyboardInterrupt:
        logger.info("Auth gate interrupted by user")
