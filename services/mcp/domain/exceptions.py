from mcp.server.mcpserver.exceptions import ToolError

from config.constants import BYTES_PER_MIB, WORKSPACE_PATH


class SandboxError(ToolError):
    pass


class SandboxUnavailableError(SandboxError):
    def __init__(self, container_name: str, reason: str) -> None:
        super().__init__(f"Sandbox container '{container_name}' is unavailable: {reason}. It may still be starting, so wait a few seconds and retry.")


class SandboxRestartedError(SandboxError):
    def __init__(self, message: str = "The sandbox restarted, so processes and shell state from before the restart are gone. Run the operation again.") -> None:
        super().__init__(message)


class SandboxExecError(SandboxError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"The sandbox rejected the command: {reason}.")


class InvalidArgumentError(SandboxError):
    pass


class ProcessNotFoundError(SandboxError):
    def __init__(self, process_id: str) -> None:
        super().__init__(f"Background process '{process_id}' is not tracked. Call background_list to see the tracked processes.")


class PathTraversalError(SandboxError):
    def __init__(self, path: str) -> None:
        super().__init__(f"{path} is outside {WORKSPACE_PATH}. The file tools only work inside it. Use shell_execute for other paths.")


class WorkspaceFileError(SandboxError):
    pass


class NotRegularFileError(WorkspaceFileError):
    def __init__(self, path: str) -> None:
        super().__init__(f"{path} is not a regular file. The file tools only work on regular files. Use shell_execute for directories, devices, sockets and FIFOs.")


class FileTooLargeError(WorkspaceFileError):
    def __init__(self, path: str, max_bytes: int) -> None:
        super().__init__(f"{path} is larger than this tool's limit of {max_bytes // BYTES_PER_MIB} MiB. Work on it in parts with shell_execute.")
