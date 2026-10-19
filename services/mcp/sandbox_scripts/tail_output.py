import sys
from typing import Final


BYTE_COUNT_MARKER: Final[str] = "__LP_BYTES__"


def write_byte_counts(total_bytes: int, next_offset: int, is_truncated: bool = False) -> None:
    sys.stdout.write(f"{BYTE_COUNT_MARKER}{total_bytes} {next_offset} {int(is_truncated)}\n")
    sys.stdout.flush()
