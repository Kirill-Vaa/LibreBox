import json
import os
import sys
from pathlib import Path
from typing import Final

from sandbox_scripts.file_access import open_regular
from sandbox_scripts.proc_stat import START_TICKS_FIELD, STATE_FIELD, ZOMBIE_STATE, parse_stat_fields


EXIT_CODE_MAX_BYTES: Final[int] = 64


def read_is_running(pid: str, start_ticks: str) -> bool:
    try:
        fields = parse_stat_fields(Path(f"/proc/{pid}/stat").read_text())
    except (OSError, IndexError):
        return False

    return bool(fields) and fields[START_TICKS_FIELD] == start_ticks and fields[STATE_FIELD] != ZOMBIE_STATE


def read_exit_code(exit_path: str) -> int | None:
    try:
        descriptor = open_regular(exit_path)
    except OSError:
        return None

    try:
        return int(os.read(descriptor, EXIT_CODE_MAX_BYTES))
    except (OSError, ValueError):
        return None
    finally:
        os.close(descriptor)


def main() -> None:
    pid, start_ticks, exit_path = sys.argv[1], sys.argv[2], sys.argv[3]
    print(json.dumps({"is_running": read_is_running(pid, start_ticks), "exit_code": read_exit_code(exit_path)}))


if __name__ == "__main__":
    main()
