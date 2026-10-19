import asyncio
import contextlib
import errno
import os
import secrets
import stat
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Final

from domain.exceptions import FileTooLargeError, NotRegularFileError, WorkspaceFileError
from infrastructure.fs.beneath import open_beneath_fd, open_directory_beneath_fd, open_workspace_root
from utils.logger import logger


READ_CHUNK_BYTES: Final[int] = 1024 * 1024
_TEMPORARY_NAME_PREFIX: Final[str] = ".libre-box-write-"


async def run_file_operation[ResultType](path: str, operation: Callable[..., ResultType], *arguments: object) -> ResultType:
    try:
        return await asyncio.to_thread(operation, *arguments)
    except OSError as os_error:
        raise describe_os_error(os_error, path) from os_error
    except LookupError as lookup_error:
        raise WorkspaceFileError(f"Unknown encoding: {lookup_error}. Pass a Python codec name, such as utf-8, utf-16 or cp1251.") from lookup_error
    except UnicodeError as unicode_error:
        raise WorkspaceFileError(f"{path} cannot be decoded or encoded with the requested encoding: {unicode_error}. Pass the encoding the file actually uses.") from unicode_error


def describe_os_error(error: OSError, path: str) -> WorkspaceFileError:
    reasons = {
        FileNotFoundError: "does not exist. Check the path, or create it first",
        IsADirectoryError: "is a directory, not a file",
        NotADirectoryError: "is not a directory, or one of its parents is a file",
        PermissionError: "cannot be accessed with the current permissions",
        FileExistsError: "already exists as a file, so it cannot be used as a directory",
    }
    reason = next((text for error_type, text in reasons.items() if isinstance(error, error_type)), error.strerror or str(error))
    return WorkspaceFileError(f"{path} {reason}.")


def require_regular_file(file_descriptor: int, path: str, max_bytes: int | None = None) -> os.stat_result:
    entry_stat = os.fstat(file_descriptor)
    if not stat.S_ISREG(entry_stat.st_mode):
        raise NotRegularFileError(path)

    if max_bytes is not None and entry_stat.st_size > max_bytes:
        raise FileTooLargeError(path, max_bytes)

    return entry_stat


def read_all(file_descriptor: int, path: str, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total_bytes = 0
    while chunk := os.read(file_descriptor, READ_CHUNK_BYTES):
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise FileTooLargeError(path, max_bytes)

        chunks.append(chunk)

    return b"".join(chunks)


def replace_file(relative_path: str, data: bytes, display_path: str) -> None:
    target_path = PurePosixPath(relative_path)
    if not target_path.name:
        raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), display_path)

    with open_workspace_root() as root_fd:
        parent_fd = open_directory_beneath_fd(root_fd, str(target_path.parent), display_path)
        try:
            _replace_in_directory(parent_fd, target_path.name, data, display_path)
        finally:
            os.close(parent_fd)


def to_display_name(name: str) -> str:
    return os.fsencode(name).decode(errors="replace")


def _replace_in_directory(parent_fd: int, name: str, data: bytes, display_path: str) -> None:
    existing_stat = _stat_existing_writable_file(parent_fd, name, display_path)
    temporary_name = f"{_TEMPORARY_NAME_PREFIX}{secrets.token_hex(8)}"
    temporary_fd = open_beneath_fd(parent_fd, temporary_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, display_path)
    is_replaced = False
    try:
        try:
            if existing_stat is not None:
                _copy_ownership_and_mode(temporary_fd, existing_stat, display_path)

            _write_all(temporary_fd, data)
            os.fsync(temporary_fd)
        finally:
            os.close(temporary_fd)

        os.replace(temporary_name, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        is_replaced = True
    finally:
        if not is_replaced:
            with contextlib.suppress(OSError):
                os.unlink(temporary_name, dir_fd=parent_fd)


def _stat_existing_writable_file(parent_fd: int, name: str, display_path: str) -> os.stat_result | None:
    try:
        file_descriptor = open_beneath_fd(parent_fd, name, os.O_WRONLY | os.O_NOFOLLOW, display_path)
    except FileNotFoundError:
        return None

    try:
        return require_regular_file(file_descriptor, display_path)
    finally:
        os.close(file_descriptor)


def _copy_ownership_and_mode(file_descriptor: int, source_stat: os.stat_result, display_path: str) -> None:
    current_stat = os.fstat(file_descriptor)
    if (current_stat.st_uid, current_stat.st_gid) != (source_stat.st_uid, source_stat.st_gid):
        try:
            os.fchown(file_descriptor, source_stat.st_uid, source_stat.st_gid)
        except PermissionError as error:
            logger.warning(f"Could not keep owner {source_stat.st_uid}:{source_stat.st_gid} of rewritten file {display_path}: {error}")

    os.fchmod(file_descriptor, stat.S_IMODE(source_stat.st_mode))


def _write_all(file_descriptor: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written_bytes = os.write(file_descriptor, remaining)
        if written_bytes == 0:
            raise OSError(errno.EIO, os.strerror(errno.EIO))

        remaining = remaining[written_bytes:]
