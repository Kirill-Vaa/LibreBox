from typing import Annotated

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from config.constants import DEFAULT_COMMAND_TIMEOUT_SECONDS, OUTPUT_CHAR_LIMIT_DEFAULT, TOOL_TIMEOUT_MAX_SECONDS, WORKSPACE_PATH
from domain.models import ShellResult
from infrastructure.docker.constants import EXEC_TIMEOUT_KILL_GRACE_SECONDS
from infrastructure.docker.sandbox_client import SandboxClient
from mcp_server.descriptions import CWD_DESCRIPTION, ENV_DESCRIPTION


def register_shell_tools(mcp: MCPServer, sandbox_client: SandboxClient, default_timeout: int = DEFAULT_COMMAND_TIMEOUT_SECONDS, output_limit: int = OUTPUT_CHAR_LIMIT_DEFAULT) -> None:

    @mcp.tool(
        description=(
            "Run a command in the sandbox with bash -lc and return stdout, stderr and the exit code. Use it for anything the file tools do not cover. "
            "Every call starts fresh. The working directory, exported variables and virtualenvs do not carry over, so chain dependent steps with && in one call. "
            "The command has no stdin. A command that waits for input blocks until the timeout, so pass answers through flags, env or a heredoc. "
            f"On timeout the command gets SIGTERM, then SIGKILL after {EXEC_TIMEOUT_KILL_GRACE_SECONDS} s, and timed_out is true. "
            f"stdout and stderr are each limited to {output_limit} characters. Longer output keeps the head and the tail. Redirect large output to a file in {WORKSPACE_PATH} and read it with file_read. "
            "All processes the command started are killed when the call returns, even ones detached with &, nohup or setsid. Start servers and other long-running jobs with background_start. "
            f"A call longer than {TOOL_TIMEOUT_MAX_SECONDS} s is not allowed, because the chat client aborts a turn after 20 minutes without output. Run longer work with background_start and poll it with background_wait. "
            "The command text is logged, so pass credentials in env."
        )
    )
    async def shell_execute(
        command: Annotated[str, Field(description="Shell command to run.")],
        cwd: Annotated[str, Field(description=CWD_DESCRIPTION)] = WORKSPACE_PATH,
        timeout: Annotated[int, Field(description=f"Seconds the command may run before it is terminated. Range: 1-{TOOL_TIMEOUT_MAX_SECONDS}. Default: {default_timeout}.", ge=1, le=TOOL_TIMEOUT_MAX_SECONDS)] = default_timeout,
        env: Annotated[dict[str, str] | None, Field(description=ENV_DESCRIPTION)] = None,
    ) -> ShellResult:
        return await sandbox_client.exec_once(command=command, workdir=cwd, timeout=timeout, environment=env)
