import asyncio
from typing import Any

from mcp.server.context import CallNext, HandlerResult, ServerMiddleware, ServerRequestContext
from mcp.shared.exceptions import MCPError
from pydantic import ValidationError

from mcp_server.constants import AUDIT_ARGUMENTS_MAX_CHARS, AUDIT_REDACTED_TOOL_ARGUMENTS, AUDIT_SECRET_ARGUMENTS, AUDIT_VALUE_PREVIEW_CHARS
from utils.logger import logger


def _render_name(name: object) -> str:
    text = str(name)
    if len(text) > AUDIT_VALUE_PREVIEW_CHARS:
        text = f"{text[:AUDIT_VALUE_PREVIEW_CHARS]}..."

    return text if text.isidentifier() else repr(text)


def _render_keys(value: dict[Any, Any]) -> str:
    return f"{{{', '.join(sorted(_render_name(key) for key in value))}}}"


def _render_value(value: object) -> str:
    if isinstance(value, str):
        return repr(value if len(value) <= AUDIT_VALUE_PREVIEW_CHARS else f"{value[:AUDIT_VALUE_PREVIEW_CHARS]}...")

    if isinstance(value, dict):
        return _render_keys(value)

    if isinstance(value, list):
        return f"[{len(value)} items]"

    return repr(value)


def _render_secret_value(value: object) -> str:
    return _render_keys(value) if isinstance(value, dict) else "<redacted>"


def _render_argument(tool_name: str, name: object, value: object) -> str:
    if name in AUDIT_SECRET_ARGUMENTS or name in AUDIT_REDACTED_TOOL_ARGUMENTS.get(tool_name, frozenset()):
        return _render_secret_value(value)

    return _render_value(value)


def _render_arguments(tool_name: str, arguments: object) -> str:
    if not isinstance(arguments, dict):
        return "-" if arguments is None else _render_value(arguments)

    parts = [f"{_render_name(name)}={_render_argument(tool_name, name, value)}" for name, value in arguments.items()]
    rendered_arguments = " ".join(parts) or "-"
    return rendered_arguments if len(rendered_arguments) <= AUDIT_ARGUMENTS_MAX_CHARS else f"{rendered_arguments[:AUDIT_ARGUMENTS_MAX_CHARS]}..."


def _is_error_result(result: HandlerResult) -> bool:
    return isinstance(result, dict) and result.get("isError") is True


class ToolCallAuditMiddleware(ServerMiddleware[Any]):
    async def __call__(self, context: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
        if context.method != "tools/call":
            return await call_next(context)

        request_params: dict[str, Any] = dict(context.params or {})
        tool_name = _render_name(request_params["name"]) if isinstance(request_params.get("name"), str) else "<unknown>"
        arguments = _render_arguments(tool_name, request_params.get("arguments"))
        logger.info(f"Tool call started tool={tool_name} arguments={arguments}")

        running_loop = asyncio.get_running_loop()
        started_at = running_loop.time()

        def elapsed_ms() -> int:
            return int((running_loop.time() - started_at) * 1000)

        try:
            result = await call_next(context)
        except MCPError as protocol_error:
            logger.warning(f"Tool call rejected tool={tool_name} duration_ms={elapsed_ms()} code={protocol_error.error.code}: {protocol_error.error.message!r}")
            raise
        except ValidationError:
            logger.warning(f"Tool call rejected tool={tool_name} duration_ms={elapsed_ms()}: invalid request parameters")
            raise
        except asyncio.CancelledError:
            logger.info(f"Tool call cancelled tool={tool_name} duration_ms={elapsed_ms()}")
            raise
        except Exception as error:
            logger.exception(f"Tool call crashed tool={tool_name} duration_ms={elapsed_ms()}: {error!r}")
            raise

        if _is_error_result(result):
            logger.warning(f"Tool call failed tool={tool_name} duration_ms={elapsed_ms()}")
        else:
            logger.info(f"Tool call finished tool={tool_name} duration_ms={elapsed_ms()}")

        return result
