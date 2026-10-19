import os
import posixpath
from pathlib import PurePosixPath
from typing import Final

from config.constants import WORKSPACE_PATH
from domain.exceptions import InvalidArgumentError, PathTraversalError


_WORKSPACE_ROOT: Final[PurePosixPath] = PurePosixPath(WORKSPACE_PATH)


def resolve_workspace_path(candidate: str) -> PurePosixPath:
    normalized = _normalize(candidate)
    if normalized != _WORKSPACE_ROOT and _WORKSPACE_ROOT not in normalized.parents:
        raise PathTraversalError(candidate)

    return normalized


def resolve_command_cwd(candidate: str) -> str:
    return str(_normalize(candidate))


def to_workspace_relative(resolved: PurePosixPath) -> str:
    relative = resolved.relative_to(_WORKSPACE_ROOT)
    return str(relative) if relative.parts else "."


def _normalize(candidate: str) -> PurePosixPath:
    if not candidate:
        raise InvalidArgumentError(f"The path is empty. Pass an absolute path or one relative to {WORKSPACE_PATH}.")

    if "\x00" in candidate:
        raise InvalidArgumentError(f"The path {candidate!r} contains a NUL character. Remove it.")

    try:
        os.fsencode(candidate)
    except UnicodeEncodeError as error:
        raise InvalidArgumentError(f"The path {candidate!r} is not a valid filesystem name: {error}.") from error

    raw_path = PurePosixPath(candidate)
    combined = raw_path if raw_path.is_absolute() else _WORKSPACE_ROOT / raw_path
    normalized = posixpath.normpath(str(combined))
    return PurePosixPath(f"/{normalized.lstrip('/')}")
