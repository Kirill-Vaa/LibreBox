import asyncio
from datetime import datetime
from typing import Annotated, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field, ValidationError

from config.constants import DEFAULT_COMMAND_TIMEOUT_SECONDS
from domain.models import SandboxInventory, SleepResult, TimeNowResult
from infrastructure.docker.sandbox_client import SandboxClient
from mcp_server.constants import SANDBOX_INVENTORY_MAX_CHARS, SANDBOX_INVENTORY_PATH, SANDBOX_INVENTORY_TIMEOUT_SECONDS, TOOL_TIMEZONE_MAX_CHARS


_COMMAND_ALIASES: Final[tuple[tuple[str, ...], ...]] = (
    ("bat", "batcat"),
    ("fd", "fdfind"),
    ("make", "gmake"),
    ("pip", "pip3"),
    ("python3", "python"),
    ("radare2", "r2"),
)


def register_system_tools(mcp: MCPServer, sandbox_client: SandboxClient, max_sleep_seconds: int = DEFAULT_COMMAND_TIMEOUT_SECONDS) -> None:

    @mcp.tool(
        description=(
            "Return a short text summary of the sandbox image profile (core, standard or full) and its main command-line tools, with aliases merged, such as fd and fdfind. Use it to see what is installed before you install or write something. "
            "It lists general-purpose tools by default. include_security adds the security tools, and include_versions adds the versions recorded when the image was built. "
            "The summary is not a full PATH listing and not a live check, so a tool missing from it may still be installed. Verify with command -v in shell_execute. "
            f"The full build-time inventory, with command paths, is the JSON file {SANDBOX_INVENTORY_PATH}. Read it with shell_execute."
        ),
        structured_output=False,
    )
    async def sandbox_inventory(
        include_security: Annotated[bool, Field(description="Also list the tools added by the image's security installation stage. Default: false.")] = False,
        include_versions: Annotated[bool, Field(description="Show the version recorded at image build time beside each tool. A tool without one shows 'version unknown'. Default: false.")] = False,
    ) -> str:
        result = await sandbox_client.exec_once(command=f"cat -- {SANDBOX_INVENTORY_PATH}", workdir="/", timeout=SANDBOX_INVENTORY_TIMEOUT_SECONDS, output_char_limit=SANDBOX_INVENTORY_MAX_CHARS, should_kill_leftovers=False)
        if result.timed_out:
            raise ToolError("Reading the sandbox inventory timed out. Check that the sandbox responds, then try again.")

        if result.exit_code != 0:
            raise ToolError(f"Could not read {SANDBOX_INVENTORY_PATH} in the sandbox. Rebuild the sandbox image to generate it. Until then, check tools with command -v in shell_execute.")

        if result.truncated:
            raise ToolError("The sandbox inventory is too large to read in one call, so the partial data was discarded. Read the file with shell_execute instead.")

        try:
            inventory = SandboxInventory.model_validate_json(result.stdout)
        except ValidationError as error:
            raise ToolError("The sandbox inventory is invalid or uses an unsupported schema. Rebuild the sandbox image. Until then, check tools with command -v in shell_execute.") from error

        toolchain_names = set(inventory.toolchain_commands)
        commands = {command.name: command for command in inventory.commands if command.name in toolchain_names and (include_security or not command.is_security)}
        for aliases in _COMMAND_ALIASES:
            available_aliases = [name for name in aliases if name in commands]
            for name in available_aliases[1:]:
                del commands[name]

        tools = [f"{name} ({command.version or 'version unknown'})" if include_versions else name for name, command in sorted(commands.items())]
        tool_list = ", ".join(tools) if tools else "none recorded"
        security = "included" if include_security else "excluded (set include_security=true to list them)"
        return f"Profile: {inventory.profile}\nTools: {tool_list}\nSecurity: {security}\nFull inventory: {SANDBOX_INVENTORY_PATH}"

    @mcp.tool(
        description=(
            f"Pause for the given number of seconds without using a sandbox shell. Use it between two checks on a background process. For a single process, background_wait is usually better. Maximum: {max_sleep_seconds} s."
        )
    )
    async def sleep(
        seconds: Annotated[float, Field(description=f"Seconds to pause. Range: 0-{max_sleep_seconds}. Fractions are allowed.", ge=0, le=max_sleep_seconds)],
    ) -> SleepResult:
        running_loop = asyncio.get_running_loop()
        started_at = running_loop.time()
        await asyncio.sleep(seconds)
        return SleepResult(slept_seconds=round(running_loop.time() - started_at, 3))

    @mcp.tool(
        description=(
            "Return the current time in a timezone as an ISO 8601 string, Unix epoch seconds and a readable string. Use it when you need the time now, because the time in your prompt does not advance as you work."
        )
    )
    async def time_now(
        timezone: Annotated[str, Field(description="IANA timezone name, such as UTC, Europe/Berlin or America/New_York. Default: UTC.", max_length=TOOL_TIMEZONE_MAX_CHARS)] = "UTC",
    ) -> TimeNowResult:
        try:
            zone = ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ToolError(f"Unknown IANA timezone {timezone!r}. Pass a name such as UTC, Europe/Berlin or America/New_York.") from error

        now = datetime.now(zone)
        return TimeNowResult(iso=now.isoformat(), epoch=now.timestamp(), human=now.strftime("%Y-%m-%d %H:%M:%S %Z"), timezone=timezone)
