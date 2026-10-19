from typing import Final


TOOL_TIMEOUT_MAX_SECONDS: Final[int] = 1195
ERROR_PREVIEW_CHARS: Final[int] = 200
BYTES_PER_MIB: Final[int] = 1024 * 1024

DEFAULT_COMMAND_TIMEOUT_SECONDS: Final[int] = 600
OUTPUT_CHAR_LIMIT_DEFAULT: Final[int] = 100000

WORKSPACE_PATH: Final[str] = "/root/data"

SANDBOX_CONTAINER_NAME: Final[str] = "libre-box-sandbox"
SANDBOX_PYTHON_PATH: Final[str] = "/usr/bin/python3"
SANDBOX_CONTAINER_NAME_REGEX: Final[str] = r"[a-zA-Z0-9][a-zA-Z0-9_.-]+"
