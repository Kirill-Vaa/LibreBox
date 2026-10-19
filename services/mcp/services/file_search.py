import asyncio
import contextlib
import os
from collections.abc import AsyncGenerator, AsyncIterator
from pathlib import PurePosixPath
from typing import Final

from config.constants import ERROR_PREVIEW_CHARS
from domain.exceptions import InvalidArgumentError, WorkspaceFileError
from domain.models import FileSearchMode, FileSearchResult
from domain.workspace import resolve_workspace_path, to_workspace_relative
from infrastructure.fs.beneath import open_directory_beneath_fd, open_workspace_root
from infrastructure.fs.landlock_exec import build_confined_command
from services.file_constants import FILE_SEARCH_LINE_LIMIT_BYTES, FILE_SEARCH_MAX_COLUMNS, FILE_SEARCH_STDERR_MAX_BYTES, FILE_SEARCH_TIMEOUT_SECONDS
from services.file_operations import describe_os_error
from utils.logger import logger


_STDERR_CHUNK_BYTES: Final[int] = 65536
_BINARY_NOTICE_MARKER: Final[bytes] = b'(found "\\0" byte around offset '
_SEARCH_ENVIRONMENT: Final[dict[str, str]] = {"PATH": os.environ.get("PATH", os.defpath)}


async def search_workspace(pattern: str, path: str, glob: str | None, mode: FileSearchMode, max_results: int) -> FileSearchResult:
    if "\x00" in pattern or (glob is not None and "\x00" in glob):
        raise InvalidArgumentError("pattern and glob must not contain a NUL character. Remove it.")

    target = resolve_workspace_path(path)
    command, success_codes = _build_search_command(pattern, glob, mode, max_results + 1)

    matches: list[str] = []
    is_limit_reached = False
    is_timed_out = False
    async with _start_search(command, to_workspace_relative(target), path) as (process, stdout, stderr):
        stderr_task = asyncio.create_task(_read_limited(stderr, FILE_SEARCH_STDERR_MAX_BYTES))
        try:
            async with asyncio.timeout(FILE_SEARCH_TIMEOUT_SECONDS), contextlib.aclosing(_read_search_records(stdout, mode)) as records:
                async for record in records:
                    if len(matches) >= max_results:
                        is_limit_reached = True
                        break

                    matches.append(_format_match(record, target))

                if not is_limit_reached:
                    await process.wait()
        except TimeoutError:
            is_timed_out = True
            logger.warning(f"Search timed out tool={command[0]} path={path} timeout={FILE_SEARCH_TIMEOUT_SECONDS}")
        except asyncio.LimitOverrunError as overrun_error:
            raise WorkspaceFileError(f"The search stopped because {command[0]} produced one result longer than {FILE_SEARCH_LINE_LIMIT_BYTES} bytes. Use glob or path to skip the file that caused it.") from overrun_error
        finally:
            await _reap(process)
            stderr_bytes = await stderr_task

        stderr_text = stderr_bytes.decode(errors="replace").strip()
        is_cut_short = is_limit_reached or is_timed_out
        if not is_cut_short and process.returncode not in success_codes:
            logger.warning(f"Search command failed tool={command[0]} code={process.returncode} stderr={stderr_text[:ERROR_PREVIEW_CHARS]!r}")
            raise WorkspaceFileError(f"The search failed. {command[0]} reported: {stderr_text or f'exit code {process.returncode}'}.")

    return FileSearchResult(matches=matches, truncated=is_limit_reached, timed_out=is_timed_out)


def _build_search_command(pattern: str, glob: str | None, mode: FileSearchMode, result_cap: int) -> tuple[list[str], tuple[int, ...]]:
    if mode == "files":
        return ["fd", "--glob", "--hidden", "--no-ignore", "--print0", "--max-results", str(result_cap), "--", pattern, "."], (0,)

    command = ["rg", "--null", "--line-number", "--no-heading", "--color", "never", "--max-count", str(result_cap), "--max-columns", str(FILE_SEARCH_MAX_COLUMNS), "--max-columns-preview"]
    if glob is not None:
        command.append(f"--glob={glob}")

    command += ["--regexp", pattern, "--", "."]
    return command, (0, 1)


@contextlib.asynccontextmanager
async def _start_search(command: list[str], relative_path: str, path: str) -> AsyncIterator[tuple[asyncio.subprocess.Process, asyncio.StreamReader, asyncio.StreamReader]]:
    root_fd, search_fd = await asyncio.to_thread(_open_search_descriptors, relative_path, path)
    try:
        process = await asyncio.create_subprocess_exec(
            *build_confined_command(root_fd, search_fd, command),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            pass_fds=(root_fd, search_fd),
            env=_SEARCH_ENVIRONMENT,
            limit=FILE_SEARCH_LINE_LIMIT_BYTES,
        )
    except OSError as error:
        raise WorkspaceFileError(f"The search tool {command[0]} could not be started: {error}. Search with shell_execute instead.") from error
    finally:
        os.close(search_fd)
        os.close(root_fd)

    try:
        if process.stdout is None or process.stderr is None:
            raise WorkspaceFileError(f"The search tool {command[0]} started without output pipes, so its results cannot be read. Search with shell_execute instead.")

        yield process, process.stdout, process.stderr
    finally:
        await _reap(process)


def _open_search_descriptors(relative_path: str, path: str) -> tuple[int, int]:
    with open_workspace_root() as root_fd:
        try:
            search_fd = open_directory_beneath_fd(root_fd, relative_path, path)
        except OSError as error:
            raise describe_os_error(error, path) from error

        try:
            return os.dup(root_fd), search_fd
        except OSError:
            os.close(search_fd)
            raise


async def _reap(process: asyncio.subprocess.Process) -> None:
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.kill()

        await process.wait()


async def _read_search_records(stream: asyncio.StreamReader, mode: FileSearchMode) -> AsyncGenerator[str]:
    while True:
        try:
            path_chunk = await stream.readuntil(b"\0")
        except asyncio.IncompleteReadError as incomplete_error:
            trailing = _drop_binary_notices(incomplete_error.partial)
            if trailing:
                yield trailing.decode(errors="replace").removesuffix("\n")

            return

        path_bytes = _drop_binary_notices(path_chunk.removesuffix(b"\0"))
        if mode == "files":
            yield path_bytes.decode(errors="replace")
            continue

        try:
            location = await stream.readuntil(b"\n")
        except asyncio.IncompleteReadError as incomplete_error:
            location = incomplete_error.partial

        yield b":".join((path_bytes, location.removesuffix(b"\n"))).decode(errors="replace")


def _drop_binary_notices(output: bytes) -> bytes:
    remainder = output
    while (marker_index := remainder.find(_BINARY_NOTICE_MARKER)) != -1:
        notice_end = remainder.find(b")\n", marker_index)
        if notice_end == -1:
            break

        remainder = remainder[notice_end + 2 :]

    return remainder


async def _read_limited(stream: asyncio.StreamReader, max_bytes: int) -> bytes:
    captured = bytearray()
    while chunk := await stream.read(_STDERR_CHUNK_BYTES):
        captured += chunk[: max(max_bytes - len(captured), 0)]

    return bytes(captured)


def _format_match(line: str, root: PurePosixPath) -> str:
    return line.replace("./", f"{root}/", 1) if line.startswith("./") else line
