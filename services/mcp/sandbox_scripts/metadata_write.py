import base64
import os
import sys
from typing import Final


_READ_BLOCK_BYTES: Final[int] = 1 << 20
_CREATING_MODES: Final[frozenset[str]] = frozenset({"first", "only"})
_FINISHING_MODES: Final[frozenset[str]] = frozenset({"last", "only"})
_FLAGS: Final[int] = os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC


def write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(descriptor, view) :]


def append_chunk(staging: str, mode: str, chunk: str) -> None:
    descriptor = os.open(staging, _FLAGS | os.O_CREAT | os.O_EXCL, 0o600) if mode in _CREATING_MODES else os.open(staging, _FLAGS | os.O_APPEND)
    try:
        write_all(descriptor, chunk.encode("ascii"))
    finally:
        os.close(descriptor)


def read_staging(staging: str) -> bytes:
    descriptor = os.open(staging, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        encoded = b""
        while block := os.read(descriptor, _READ_BLOCK_BYTES):
            encoded += block

        return encoded
    finally:
        os.close(descriptor)


def commit(path: str, staging: str) -> None:
    data = base64.b64decode(read_staging(staging), validate=True)
    temporary = f"{path}.new"
    descriptor = os.open(temporary, _FLAGS | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        write_all(descriptor, data)
    finally:
        os.close(descriptor)

    os.replace(temporary, path)
    os.unlink(staging)


def main() -> None:
    path, mode, chunk = sys.argv[1], sys.argv[2], sys.argv[3]
    staging = f"{path}.b64"
    append_chunk(staging, mode, chunk)
    if mode in _FINISHING_MODES:
        commit(path, staging)


if __name__ == "__main__":
    main()
