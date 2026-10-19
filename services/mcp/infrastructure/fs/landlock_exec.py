import ctypes
import os
import shutil
import sys
import sysconfig
from typing import Final


_SYS_LANDLOCK_CREATE_RULESET: Final[int] = 444
_SYS_LANDLOCK_ADD_RULE: Final[int] = 445
_SYS_LANDLOCK_RESTRICT_SELF: Final[int] = 446
_LANDLOCK_CREATE_RULESET_VERSION: Final[int] = 1
_LANDLOCK_RULE_PATH_BENEATH: Final[int] = 1
_LANDLOCK_ACCESS_FS_EXECUTE: Final[int] = 1 << 0
_LANDLOCK_ACCESS_FS_READ_FILE: Final[int] = 1 << 2
_LANDLOCK_ACCESS_FS_READ_DIR: Final[int] = 1 << 3
_LANDLOCK_HANDLED_ACCESS_FS_BIT_COUNTS: Final[tuple[int, ...]] = (13, 14, 15, 15, 16, 16, 16, 16, 17)
_LANDLOCK_HANDLED_ACCESS_NET_BIT_COUNTS: Final[tuple[int, ...]] = (0, 0, 0, 2, 2, 2, 2, 2, 2, 4)
_LANDLOCK_HANDLED_SCOPE_BIT_COUNTS: Final[tuple[int, ...]] = (0, 0, 0, 0, 0, 2)
_LANDLOCK_MIN_ABI_VERSION: Final[int] = 3
_PR_SET_NO_NEW_PRIVS: Final[int] = 38
_SETUP_FAILURE_EXIT_CODE: Final[int] = 125

_libc: Final[ctypes.CDLL] = ctypes.CDLL(None, use_errno=True)
_libc.syscall.restype = ctypes.c_long


class _RulesetAttr(ctypes.Structure):
    _fields_ = (("handled_access_fs", ctypes.c_uint64), ("handled_access_net", ctypes.c_uint64), ("scoped", ctypes.c_uint64))


class _PathBeneathAttr(ctypes.Structure):
    _layout_ = "ms"
    _pack_ = 1
    _fields_ = (("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32))


def build_confined_command(workspace_fd: int, cwd_fd: int, command: list[str]) -> list[str]:
    return [sys.executable, "-I", __file__, str(workspace_fd), str(cwd_fd), *command]


def restrict_to_workspace(workspace_fd: int, executable: str) -> None:
    if not sys.platform.startswith("linux"):
        raise OSError(f"Landlock confinement is Linux-only, this is {sys.platform}")

    abi_version = _landlock_abi_version()
    if abi_version < _LANDLOCK_MIN_ABI_VERSION:
        raise OSError(f"Landlock ABI {abi_version} is below the required {_LANDLOCK_MIN_ABI_VERSION}, which is the first that can handle TRUNCATE. A confined tool could truncate workspace files")

    multiarch = sysconfig.get_config_var("MULTIARCH")
    if not multiarch:
        raise OSError("Python reports no MULTIARCH triplet, so the system library directory cannot be granted without opening all of /usr/lib")

    ruleset = _RulesetAttr(
        handled_access_fs=_supported_mask(_LANDLOCK_HANDLED_ACCESS_FS_BIT_COUNTS, abi_version),
        handled_access_net=_supported_mask(_LANDLOCK_HANDLED_ACCESS_NET_BIT_COUNTS, abi_version),
        scoped=_supported_mask(_LANDLOCK_HANDLED_SCOPE_BIT_COUNTS, abi_version),
    )
    ruleset_fd = _check(_libc.syscall(ctypes.c_long(_SYS_LANDLOCK_CREATE_RULESET), ctypes.byref(ruleset), ctypes.c_size_t(ctypes.sizeof(ruleset)), ctypes.c_uint32(0)), "landlock_create_ruleset")
    try:
        _add_rule(ruleset_fd, workspace_fd, _LANDLOCK_ACCESS_FS_READ_FILE | _LANDLOCK_ACCESS_FS_READ_DIR)
        for runtime_path in (executable, f"/usr/lib/{multiarch}"):
            runtime_fd = os.open(runtime_path, os.O_RDONLY | os.O_CLOEXEC)
            try:
                _add_rule(ruleset_fd, runtime_fd, _LANDLOCK_ACCESS_FS_EXECUTE | _LANDLOCK_ACCESS_FS_READ_FILE)
            finally:
                os.close(runtime_fd)

        _check(_libc.prctl(ctypes.c_int(_PR_SET_NO_NEW_PRIVS), ctypes.c_ulong(1), ctypes.c_ulong(0), ctypes.c_ulong(0), ctypes.c_ulong(0)), "prctl(PR_SET_NO_NEW_PRIVS)")
        _check(_libc.syscall(ctypes.c_long(_SYS_LANDLOCK_RESTRICT_SELF), ctypes.c_int(ruleset_fd), ctypes.c_uint32(0)), "landlock_restrict_self")
    finally:
        os.close(ruleset_fd)


def _verify_search_directory() -> None:
    try:
        with os.scandir(".") as entries:
            next(entries, None)
    except OSError as error:
        raise OSError(f"The search directory cannot be read under Landlock: {error}") from error


def _landlock_abi_version() -> int:
    return _check(_libc.syscall(ctypes.c_long(_SYS_LANDLOCK_CREATE_RULESET), None, ctypes.c_size_t(0), ctypes.c_uint32(_LANDLOCK_CREATE_RULESET_VERSION)), "landlock_create_ruleset")


def _supported_mask(bit_counts: tuple[int, ...], abi_version: int) -> int:
    return (1 << bit_counts[min(abi_version, len(bit_counts)) - 1]) - 1


def _add_rule(ruleset_fd: int, parent_fd: int, allowed_access: int) -> None:
    rule = _PathBeneathAttr(allowed_access=allowed_access, parent_fd=parent_fd)
    _check(_libc.syscall(ctypes.c_long(_SYS_LANDLOCK_ADD_RULE), ctypes.c_int(ruleset_fd), ctypes.c_int(_LANDLOCK_RULE_PATH_BENEATH), ctypes.byref(rule), ctypes.c_uint32(0)), "landlock_add_rule")


def _check(result: int, operation: str) -> int:
    if result < 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, f"{operation}: {os.strerror(error_number)}")

    return result


def main() -> None:
    command = sys.argv[3:]
    try:
        workspace_fd, cwd_fd = int(sys.argv[1]), int(sys.argv[2])
        executable = shutil.which(command[0])
        if executable is None:
            raise FileNotFoundError(f"{command[0]} is not installed")

        os.fchdir(cwd_fd)
        restrict_to_workspace(workspace_fd, executable)
        _verify_search_directory()
        for inherited_fd in {workspace_fd, cwd_fd}:
            os.close(inherited_fd)

        os.execve(executable, command, {"PATH": os.environ.get("PATH", os.defpath)})
    except Exception as error:
        tool = command[0] if command else "the search tool"
        sys.stderr.write(f"Cannot start {tool} confined to the workspace with Landlock (Linux 6.2+ with Landlock enabled is required): {error or type(error).__name__}. Search with shell_execute instead\n")
        sys.exit(_SETUP_FAILURE_EXIT_CODE)


if __name__ == "__main__":
    main()
