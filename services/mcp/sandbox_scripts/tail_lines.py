import os
import sys
from typing import Final

from sandbox_scripts.file_access import open_regular_or_exit
from sandbox_scripts.tail_output import write_byte_counts


READ_BLOCK_BYTES: Final[int] = 65536
MAX_CONTINUATION_BYTES: Final[int] = 3
CONTINUATION_MASK: Final[int] = 0xC0
CONTINUATION_PREFIX: Final[int] = 0x80


def find_tail_start(descriptor: int, size: int, lines: int) -> int:
    remaining = lines + 1 if size and os.pread(descriptor, 1, size - 1) == b"\n" else lines
    start = size
    while start > 0:
        block_start = max(start - READ_BLOCK_BYTES, 0)
        block = os.pread(descriptor, start - block_start, block_start)
        count = block.count(b"\n")
        if count >= remaining:
            index = len(block)
            for _ in range(remaining):
                index = block.rindex(b"\n", 0, index)

            return block_start + index + 1

        remaining -= count
        start = block_start

    return start


def skip_partial_sequence(descriptor: int, position: int, size: int) -> int:
    skipped = 0
    while position < size and skipped < MAX_CONTINUATION_BYTES and os.pread(descriptor, 1, position)[0] & CONTINUATION_MASK == CONTINUATION_PREFIX:
        position += 1
        skipped += 1

    return position


def main() -> None:
    path, lines, max_bytes = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    descriptor = open_regular_or_exit(path)
    size = os.fstat(descriptor).st_size
    position = find_tail_start(descriptor, size, lines)
    is_truncated = size - position > max_bytes
    if is_truncated:
        position = skip_partial_sequence(descriptor, size - max_bytes, size)

    write_byte_counts(size, size, is_truncated)
    while position < size:
        data = os.pread(descriptor, min(READ_BLOCK_BYTES, size - position), position)
        if not data:
            break

        sys.stdout.buffer.write(data)
        position += len(data)


if __name__ == "__main__":
    main()
