import os
import sys
from typing import Final

from sandbox_scripts.file_access import open_regular_or_exit
from sandbox_scripts.tail_output import write_byte_counts


_MAX_UTF8_SEQUENCE_BYTES: Final[int] = 4
_CONTINUATION_MASK: Final[int] = 0xC0
_CONTINUATION_PREFIX: Final[int] = 0x80


def sequence_width(byte: int) -> int:
    if byte & 0xE0 == 0xC0:
        return 2

    if byte & 0xF0 == 0xE0:
        return 3

    if byte & 0xF8 == 0xF0:
        return 4

    return 1


def trim_partial_sequence(data: bytes) -> bytes:
    for index in range(1, min(_MAX_UTF8_SEQUENCE_BYTES, len(data)) + 1):
        byte = data[-index]
        if byte & _CONTINUATION_MASK == _CONTINUATION_PREFIX:
            continue

        trim = index if sequence_width(byte) > index else 0
        return data[:-trim] if 0 < trim < len(data) else data

    return data


def main() -> None:
    path, offset, chunk = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    descriptor = open_regular_or_exit(path)
    size = os.fstat(descriptor).st_size
    data = os.pread(descriptor, min(chunk, size - offset), offset) if offset < size else b""
    data = trim_partial_sequence(data)
    write_byte_counts(size, offset + len(data))
    sys.stdout.buffer.write(data)


if __name__ == "__main__":
    main()
