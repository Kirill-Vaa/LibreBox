import inspect
import logging
import sys
from pathlib import Path
from typing import Final

from loguru import logger


__all__: list[str] = ["configure_logging", "logger"]


_LOG_DIRECTORY: Final[Path] = Path(__file__).resolve().parent.parent / "logs"
_ARCHIVE_RETENTION_DAYS: Final[int] = 14
_ROTATION_SIZE: Final[str] = "100 MB"
_STDOUT_FORMAT: Final[str] = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <magenta>{extra[request_id]}</magenta> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
)
_FILE_FORMAT: Final[str] = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {extra[request_id]} | {name}:{function}:{line} - {message}"
_INTERCEPTED_LOGGER_NAMES: Final[tuple[str, ...]] = ("asyncio", "mcp", "uvicorn", "uvicorn.access", "uvicorn.error")
_QUIETED_LOGGER_LEVELS: Final[dict[str, int]] = {"mcp.server.streamable_http": logging.WARNING}


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = inspect.currentframe(), 0
        while frame is not None and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _add_console_sink(log_level: str) -> int:
    return logger.add(sys.stdout, level=log_level, format=_STDOUT_FORMAT, colorize=True, enqueue=True, backtrace=True, diagnose=False)


def _install_stdlib_intercept() -> None:
    logging.basicConfig(handlers=[_InterceptHandler()], level=logging.NOTSET, force=True)
    for intercepted_logger_name in _INTERCEPTED_LOGGER_NAMES:
        intercepted_logger = logging.getLogger(intercepted_logger_name)
        intercepted_logger.handlers.clear()
        intercepted_logger.propagate = True

    for quieted_logger_name, quieted_logger_level in _QUIETED_LOGGER_LEVELS.items():
        logging.getLogger(quieted_logger_name).setLevel(quieted_logger_level)


logger.remove()
logger.configure(extra={"request_id": "-"})
_console_sink_id: int = _add_console_sink("INFO")
_install_stdlib_intercept()


def configure_logging(log_level: str, should_serialize: bool, log_file_name: str = "mcp.log") -> None:
    global _console_sink_id
    logger.remove(_console_sink_id)
    _console_sink_id = _add_console_sink(log_level)

    _LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    logger.add(
        _LOG_DIRECTORY / log_file_name,
        level=log_level,
        format=_FILE_FORMAT,
        serialize=should_serialize,
        rotation=_ROTATION_SIZE,
        retention=f"{_ARCHIVE_RETENTION_DAYS} days",
        compression="zip",
        enqueue=True,
        backtrace=True,
        diagnose=False,
    )
