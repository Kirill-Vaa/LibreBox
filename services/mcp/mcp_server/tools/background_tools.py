from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from config.constants import DEFAULT_COMMAND_TIMEOUT_SECONDS, OUTPUT_CHAR_LIMIT_DEFAULT, TOOL_TIMEOUT_MAX_SECONDS, WORKSPACE_PATH
from domain.models import BackgroundListResult, BackgroundProcessInfo, BackgroundTailResult, BackgroundWaitResult, SignalName
from mcp_server.descriptions import CWD_DESCRIPTION, ENV_DESCRIPTION
from services.background_constants import BACKGROUND_GATE_TIMEOUT_EXIT_CODE, BACKGROUND_LOG_DIR, BACKGROUND_LOG_LIMIT_FAILED_EXIT_CODE, BACKGROUND_LOG_MAX_BYTES, BACKGROUND_MAX_TRACKED_PROCESSES, BACKGROUND_PROCESS_ID_LENGTH, BACKGROUND_STOP_DEFAULT_TIMEOUT_SECONDS, BACKGROUND_TAIL_DEFAULT_LINES, BACKGROUND_TAIL_MAX_LINES
from services.background_service import BackgroundService


ProcessId = Annotated[str, Field(description="ID of the background process, as returned by background_start.", max_length=BACKGROUND_PROCESS_ID_LENGTH)]


def register_background_tools(mcp: MCPServer, background_service: BackgroundService, default_timeout: int = DEFAULT_COMMAND_TIMEOUT_SECONDS, output_limit: int = OUTPUT_CHAR_LIMIT_DEFAULT) -> None:

    @mcp.tool(
        description=(
            "Start a long-running command (a server, build, scan, download or training run) in the background with bash -lc and return its process_id at once. Use it instead of shell_execute for anything that outlives one call. "
            "Next, check the process with background_tail, background_status or background_wait. "
            "A command that detaches itself into the background (a daemon, or playwright-cli open) ends the task at once: the status becomes exited, and background_stop cannot stop the detached process if it left the process group. "
            f"stdout and stderr go together to {BACKGROUND_LOG_DIR}/<process_id>.log. Read it with background_tail, because the file tools cannot reach that directory. "
            f"A sandbox reset erases the log, so write results you want to keep into {WORKSPACE_PATH}. "
            f"Every file the command writes is limited to {BACKGROUND_LOG_MAX_BYTES // (1024 * 1024 * 1024)} GiB. A command that exceeds it is killed with SIGXFSZ. "
            f"If the launcher itself fails, the log has a line starting with 'libre-box:' and the exit code is {BACKGROUND_GATE_TIMEOUT_EXIT_CODE} or {BACKGROUND_LOG_LIMIT_FAILED_EXIT_CODE}. A command can exit with those codes too, so check the log. "
            "background_list shows the command text, so pass credentials in env."
        )
    )
    async def background_start(
        command: Annotated[str, Field(description="Shell command to run.")],
        cwd: Annotated[str, Field(description=CWD_DESCRIPTION)] = WORKSPACE_PATH,
        env: Annotated[dict[str, str] | None, Field(description=ENV_DESCRIPTION)] = None,
    ) -> BackgroundProcessInfo:
        return await background_service.start(command=command, cwd=cwd, environment=env or {})

    @mcp.tool(
        description=(
            "Return the current state of one background process: status, and exit_code once it has exited. "
            "status is running, exited, lost or sandbox_restarted. lost: the process vanished without an exit code. sandbox_restarted: the sandbox restarted after the start, so the process is gone. The log stays readable with background_tail unless the sandbox was recreated."
        )
    )
    async def background_status(
        process_id: ProcessId,
    ) -> BackgroundProcessInfo:
        return await background_service.status(process_id)

    @mcp.tool(
        description=(
            "Read the log of a background process. It has two modes. "
            "Last-lines mode (offset_bytes omitted) returns the last lines. "
            "Offset mode returns the bytes after offset_bytes, to follow the log step by step. "
            "A large range comes back in chunks, so keep passing next_offset as offset_bytes until it equals total_bytes. "
            f"One call returns about {output_limit} characters at most. In last-lines mode, truncated=true means only the end of the requested lines is returned. Read the earlier part with offset_bytes=0. "
            "The log can be read while the process runs, after it exits and after a sandbox restart. A sandbox reset, which recreates the sandbox, erases it."
        )
    )
    async def background_tail(
        process_id: ProcessId,
        lines: Annotated[int, Field(description=f"Number of last lines to return. Range: 1-{BACKGROUND_TAIL_MAX_LINES}. Ignored if offset_bytes is set. Default: {BACKGROUND_TAIL_DEFAULT_LINES}.", ge=1, le=BACKGROUND_TAIL_MAX_LINES)] = BACKGROUND_TAIL_DEFAULT_LINES,
        offset_bytes: Annotated[int | None, Field(description="Byte offset to read from, normally next_offset from the previous call. Minimum: 0. Default: omitted, which returns the last lines.", ge=0)] = None,
    ) -> BackgroundTailResult:
        return await background_service.tail(process_id=process_id, lines=lines, offset_bytes=offset_bytes)

    @mcp.tool(
        description=(
            "Send a signal to the whole process group of a background process and return its status afterwards. "
            "TERM, INT, QUIT and KILL end the process. The call waits for it to exit and sends KILL if it is still running after timeout. "
            "HUP, USR1, USR2, STOP and CONT are sent without waiting, so the status stays running. STOP suspends the process and CONT resumes it. "
            "Stopping a process that has already exited is not an error."
        )
    )
    async def background_stop(
        process_id: ProcessId,
        signal: Annotated[SignalName, Field(description="Signal to send. Default: TERM.")] = "TERM",
        timeout: Annotated[int, Field(description=f"Seconds to wait for the process to exit before sending KILL. Range: 0-{TOOL_TIMEOUT_MAX_SECONDS}. Ignored for HUP, USR1, USR2, STOP and CONT. Default: {BACKGROUND_STOP_DEFAULT_TIMEOUT_SECONDS}.", ge=0, le=TOOL_TIMEOUT_MAX_SECONDS)] = BACKGROUND_STOP_DEFAULT_TIMEOUT_SECONDS,
    ) -> BackgroundProcessInfo:
        return await background_service.stop(process_id=process_id, signal=signal, timeout=timeout)

    @mcp.tool(
        description=(
            f"Wait until a background process exits or timeout passes, then return its status, exit_code and the last {BACKGROUND_TAIL_DEFAULT_LINES} lines of its log as tail. "
            "On timeout the status is running and exit_code is null. The process keeps running, so call background_wait again or poll with background_status. "
            "truncated=true means only the end of tail is returned. Read the rest with background_tail."
        )
    )
    async def background_wait(
        process_id: ProcessId,
        timeout: Annotated[int, Field(description=f"Seconds to wait for the process to exit. Range: 0-{TOOL_TIMEOUT_MAX_SECONDS}. The maximum stays below the chat client's 20-minute no-output limit. To wait longer, call background_wait again. Default: {default_timeout}.", ge=0, le=TOOL_TIMEOUT_MAX_SECONDS)] = default_timeout,
    ) -> BackgroundWaitResult:
        return await background_service.wait(process_id=process_id, timeout=timeout)

    @mcp.tool(
        description=(
            "List the tracked background processes with command, status and exit_code. Use it to find a process_id you lost. "
            f"At most {BACKGROUND_MAX_TRACKED_PROCESSES} processes are tracked. Beyond that, the oldest finished ones are dropped from the list, and running ones are always kept."
        )
    )
    async def background_list() -> BackgroundListResult:
        return BackgroundListResult(processes=await background_service.list_processes())
