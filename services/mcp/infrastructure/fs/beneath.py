import contextlib
import ctypes
import errno
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

from config.constants import WORKSPACE_PATH
from domain.exceptions import InvalidArgumentError, NotRegularFileError, WorkspaceFileError


_SYS_OPENAT2: Final[int] = 437
_OPENAT2_RESOLVE_NO_MAGICLINKS: Final[int] = 0x02
_OPENAT2_RESOLVE_BENEATH: Final[int] = 0x08
_RESOLVE_FLAGS: Final[int] = _OPENAT2_RESOLVE_BENEATH | _OPENAT2_RESOLVE_NO_MAGICLINKS
_RETRYABLE_ERROR_NUMBERS: Final[frozenset[int]] = frozenset({errno.EAGAIN, errno.EINTR})
_MAX_OPEN_ATTEMPTS: Final[int] = 16
_libc: Final[ctypes.CDLL] = ctypes.CDLL(None, use_errno=True)
_libc.syscall.restype = ctypes.c_long


class _OpenHow(ctypes.Structure):
    _fields_ = (("flags", ctypes.c_uint64), ("mode", ctypes.c_uint64), ("resolve", ctypes.c_uint64))


def _openat2(dir_fd: int, relative_path: str, flags: int, mode: int, display_path: str) -> int:
    if not sys.platform.startswith("linux"):
        raise WorkspaceFileError(f"Cannot open {display_path}. The file tools need the Linux openat2 syscall, which this host does not provide.")

    if "\x00" in relative_path:
        raise InvalidArgumentError(f"The path {relative_path!r} contains a NUL character. Remove it.")

    effective_mode = mode if flags & os.O_CREAT else 0
    how = _OpenHow(flags=flags | os.O_CLOEXEC | os.O_NONBLOCK | os.O_NOCTTY, mode=effective_mode, resolve=_RESOLVE_FLAGS)
    encoded_path = os.fsencode(relative_path)
    error_number = errno.EAGAIN
    for _ in range(_MAX_OPEN_ATTEMPTS):
        file_descriptor = _libc.syscall(ctypes.c_long(_SYS_OPENAT2), ctypes.c_int(dir_fd), encoded_path, ctypes.byref(how), ctypes.c_size_t(ctypes.sizeof(how)))
        if file_descriptor >= 0:
            return int(file_descriptor)

        error_number = ctypes.get_errno()
        if error_number not in _RETRYABLE_ERROR_NUMBERS:
            break

    if error_number == errno.EAGAIN:
        raise WorkspaceFileError(f"{display_path} kept being renamed or remounted while it was opened. Retry once it stops changing.")

    if error_number == errno.EXDEV:
        raise WorkspaceFileError(f"{display_path} leaves {WORKSPACE_PATH} through '..' or a symlink. Absolute symlinks are refused even if they point back inside it. Pass the real target path, or use shell_execute.")

    if error_number == errno.ELOOP:
        raise WorkspaceFileError(f"{display_path} is a symlink or passes through too many links. The file tools do not write through symlinks. Pass the target path, or use shell_execute.")

    if error_number == errno.ENXIO:
        raise NotRegularFileError(display_path)

    raise OSError(error_number, os.strerror(error_number), display_path)


@contextmanager
def open_workspace_root() -> Iterator[int]:
    try:
        root_fd = os.open(WORKSPACE_PATH, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    except OSError as error:
        raise WorkspaceFileError(f"The workspace {WORKSPACE_PATH} is unavailable: {error}. The file tools cannot run until it is mounted again.") from error

    try:
        yield root_fd
    finally:
        os.close(root_fd)


@contextmanager
def open_beneath(relative_path: str, flags: int, display_path: str, mode: int = 0o644) -> Iterator[int]:
    with open_workspace_root() as root_fd:
        file_descriptor = open_beneath_fd(root_fd, relative_path, flags, display_path, mode)
        try:
            yield file_descriptor
        finally:
            os.close(file_descriptor)


def open_beneath_fd(dir_fd: int, relative_path: str, flags: int, display_path: str, mode: int = 0o644) -> int:
    return _openat2(dir_fd, relative_path or ".", flags, mode, display_path)


def open_directory_beneath_fd(dir_fd: int, relative_path: str, display_path: str) -> int:
    return open_beneath_fd(dir_fd, relative_path, os.O_RDONLY | os.O_DIRECTORY, display_path)


def make_directory_beneath(relative_path: str, should_create_parents: bool, display_path: str) -> None:
    components = [component for component in relative_path.split("/") if component not in ("", ".")]
    if not components:
        return

    with open_workspace_root() as root_fd:
        parent_fd = open_directory_beneath_fd(root_fd, ".", display_path)
        try:
            for depth, component in enumerate(components):
                is_leaf = depth == len(components) - 1
                prefix = "/".join(components[: depth + 1])
                try:
                    next_fd = open_directory_beneath_fd(root_fd, prefix, display_path)
                except FileNotFoundError as error:
                    if not should_create_parents and not is_leaf:
                        raise WorkspaceFileError(f"A parent directory of {display_path} does not exist. Pass parents=true to create the missing levels.") from error

                    with contextlib.suppress(FileExistsError):
                        os.mkdir(component, mode=0o755, dir_fd=parent_fd)

                    try:
                        next_fd = open_directory_beneath_fd(root_fd, prefix, display_path)
                    except FileNotFoundError as file_not_found_error:
                        raise WorkspaceFileError(f"{prefix} cannot be used as a directory, most likely because it is a dangling symlink, so {display_path} cannot be created. Remove the link or create its target first.") from file_not_found_error

                os.close(parent_fd)
                parent_fd = next_fd
        finally:
            os.close(parent_fd)
