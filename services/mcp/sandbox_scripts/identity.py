import sys
from pathlib import Path
from typing import Final

from sandbox_scripts.proc_stat import START_TICKS_FIELD, parse_stat_fields


IDENTITY_MARKER: Final[str] = "__LP_IDENTITY__"
IDENTITY_FAILED_EXIT_CODE: Final[int] = 70


def main() -> None:
    pid = sys.argv[1]
    try:
        start_ticks = parse_stat_fields(Path(f"/proc/{pid}/stat").read_text())[START_TICKS_FIELD]
    except (OSError, IndexError, ValueError) as error:
        print(f"Could not read the identity of process {pid}: {type(error).__name__}", file=sys.stderr)
        sys.exit(IDENTITY_FAILED_EXIT_CODE)

    print(f"{IDENTITY_MARKER} {start_ticks} {pid}")


if __name__ == "__main__":
    main()
