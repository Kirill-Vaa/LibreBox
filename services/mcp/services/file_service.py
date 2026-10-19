import codecs
import os
from pathlib import PurePosixPath

from config.constants import BYTES_PER_MIB
from domain.exceptions import FileTooLargeError, WorkspaceFileError
from domain.models import DirectoryResult, DirectoryTreeResult, FileEditResult, FileReadResult, FileSearchMode, FileSearchResult, FileWriteResult
from domain.workspace import resolve_workspace_path, to_workspace_relative
from infrastructure.fs.beneath import make_directory_beneath, open_beneath
from services.file_constants import FILE_EDIT_MAX_BYTES, FILE_READ_BINARY_SNIFF_BYTES, FILE_READ_LINE_CUT_RESERVE_CHARS, FILE_READ_MAX_BYTES, FILE_READ_MAX_CONTENT_CHARS, FILE_READ_NUL_CODEC_PREFIXES
from services.file_operations import READ_CHUNK_BYTES, read_all, replace_file, require_regular_file, run_file_operation
from services.file_search import search_workspace
from services.file_tree import build_directory_tree


def _line_cut_marker(omitted_chars: int) -> str:
    return f" [... {omitted_chars} chars truncated ...]"


class _LineWindow:
    def __init__(self, offset: int, limit: int, char_budget: int) -> None:
        self._start = offset
        self._end = offset + limit
        self._char_budget = char_budget
        self._used_chars = 0
        self._line_index = 0
        self._current_parts: list[str] = []
        self._has_partial_line = False
        self._is_line_cut = False
        self._omitted_chars = 0
        self.lines: list[str] = []
        self.is_truncated = False

    @property
    def line_count(self) -> int:
        return self._line_index + (1 if self._has_partial_line else 0)

    def feed(self, text: str) -> None:
        newline_count = text.count("\n")
        if newline_count == 0:
            self._append_to_line(text)
            return

        if self._line_index >= self._end or self._line_index + newline_count < self._start:
            self._line_index += newline_count
            self._reset_line()
            self._append_to_line(text[text.rfind("\n") + 1 :])
            return

        *complete_pieces, trailing_piece = text.split("\n")
        for piece in complete_pieces:
            self._append_to_line(piece)
            self._finish_line()

        self._append_to_line(trailing_piece)

    def close(self) -> None:
        if self._has_partial_line:
            self._finish_line()

    def _append_to_line(self, piece: str) -> None:
        if not piece:
            return

        self._has_partial_line = True
        if not self._start <= self._line_index < self._end:
            return

        if self._is_line_cut:
            self._omitted_chars += len(piece)
            return

        room = self._char_budget - self._used_chars - self._prefix_chars() - FILE_READ_LINE_CUT_RESERVE_CHARS
        if len(piece) > room:
            self.is_truncated = True
            self._is_line_cut = True
            kept_piece = piece[: max(room, 0)]
            self._omitted_chars += len(piece) - len(kept_piece)
            piece = kept_piece

        self._used_chars += len(piece)
        if piece:
            self._current_parts.append(piece)

    def _finish_line(self) -> None:
        if self._start <= self._line_index < self._end:
            line = "".join(self._current_parts)
            if self._is_line_cut:
                line += _line_cut_marker(self._omitted_chars)
            else:
                line = line.removesuffix("\r")

            self.lines.append(line)
            self._used_chars += self._prefix_chars() + (len(_line_cut_marker(self._omitted_chars)) if self._is_line_cut else 0)
            if self._char_budget - self._used_chars < 2 * FILE_READ_LINE_CUT_RESERVE_CHARS or self._is_line_cut:
                self.is_truncated = True
                self._end = self._line_index + 1

        self._line_index += 1
        self._reset_line()

    def _prefix_chars(self) -> int:
        return len(str(self._line_index + 1)) + 2

    def _reset_line(self) -> None:
        self._current_parts = []
        self._has_partial_line = False
        self._is_line_cut = False
        self._omitted_chars = 0


class FileService:
    async def read(self, path: str, offset: int, limit: int, encoding: str) -> FileReadResult:
        target = resolve_workspace_path(path)
        return await run_file_operation(path, self._read_sync, target, path, offset, limit, encoding)

    async def write(self, path: str, content: str, should_create_dirs: bool, encoding: str) -> FileWriteResult:
        target = resolve_workspace_path(path)
        return await run_file_operation(path, self._write_sync, target, path, content, should_create_dirs, encoding)

    async def edit(self, path: str, old_string: str, new_string: str, should_replace_all: bool, encoding: str) -> FileEditResult:
        target = resolve_workspace_path(path)
        return await run_file_operation(path, self._edit_sync, target, path, old_string, new_string, should_replace_all, encoding)

    async def search(self, pattern: str, path: str, glob: str | None, mode: FileSearchMode, max_results: int) -> FileSearchResult:
        return await search_workspace(pattern, path, glob, mode, max_results)

    async def create_directory(self, path: str, should_create_parents: bool) -> DirectoryResult:
        target = resolve_workspace_path(path)
        await run_file_operation(path, make_directory_beneath, to_workspace_relative(target), should_create_parents, path)
        return DirectoryResult(path=str(target))

    async def tree(self, path: str, max_depth: int, should_show_hidden: bool, should_show_sizes: bool) -> DirectoryTreeResult:
        return await build_directory_tree(path, max_depth, should_show_hidden, should_show_sizes)

    def _read_sync(self, target: PurePosixPath, path: str, offset: int, limit: int, encoding: str) -> FileReadResult:
        is_nul_codec = self._text_codec_name(encoding).startswith(FILE_READ_NUL_CODEC_PREFIXES)
        decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
        window = _LineWindow(offset, limit, FILE_READ_MAX_CONTENT_CHARS)
        total_bytes = 0

        with open_beneath(to_workspace_relative(target), os.O_RDONLY, path) as file_descriptor:
            require_regular_file(file_descriptor, path, FILE_READ_MAX_BYTES)
            while chunk := os.read(file_descriptor, READ_CHUNK_BYTES):
                if total_bytes == 0 and not is_nul_codec and b"\x00" in chunk[:FILE_READ_BINARY_SNIFF_BYTES]:
                    return FileReadResult(path=str(target), content="", is_binary=True, size_bytes=os.fstat(file_descriptor).st_size, line_count=0, next_offset=offset)

                total_bytes += len(chunk)
                if total_bytes > FILE_READ_MAX_BYTES:
                    raise FileTooLargeError(path, FILE_READ_MAX_BYTES)

                window.feed(decoder.decode(chunk))

        window.feed(decoder.decode(b"", final=True))
        window.close()

        numbered_content = "\n".join(f"{offset + index + 1}\t{line}" for index, line in enumerate(window.lines))
        return FileReadResult(path=str(target), content=numbered_content, is_binary=False, size_bytes=total_bytes, line_count=window.line_count, next_offset=offset + len(window.lines), truncated=window.is_truncated)

    def _write_sync(self, target: PurePosixPath, path: str, content: str, should_create_dirs: bool, encoding: str) -> FileWriteResult:
        relative_path = to_workspace_relative(target)
        if should_create_dirs:
            parent = str(PurePosixPath(relative_path).parent)
            make_directory_beneath(parent, True, path)

        data = content.encode(encoding)
        replace_file(relative_path, data, path)
        return FileWriteResult(path=str(target), bytes_written=len(data))

    def _edit_sync(self, target: PurePosixPath, path: str, old_string: str, new_string: str, should_replace_all: bool, encoding: str) -> FileEditResult:
        if not old_string:
            raise WorkspaceFileError("old_string is empty. Pass the exact text to replace, or use file_write to replace the whole file.")

        relative_path = to_workspace_relative(target)
        with open_beneath(relative_path, os.O_RDONLY | os.O_NOFOLLOW, path) as file_descriptor:
            require_regular_file(file_descriptor, path, FILE_EDIT_MAX_BYTES)
            raw_bytes = read_all(file_descriptor, path, FILE_EDIT_MAX_BYTES)

        try:
            text = raw_bytes.decode(encoding)
        except UnicodeDecodeError as error:
            raise WorkspaceFileError(f"{path} does not decode as {encoding} text: {error}. Pass the right encoding, or use shell_execute if the file is binary.") from error

        if text.encode(encoding) != raw_bytes:
            raise WorkspaceFileError(f"{path} would not keep its exact bytes when saved as {encoding}, so the edit would change more than old_string. Pass a codec that round-trips, such as utf-8, utf-16-le, utf-16-be or latin-1, or use shell_execute.")

        original_size = len(raw_bytes)
        del raw_bytes

        occurrences = text.count(old_string)
        if occurrences == 0 and "\r\n" in text and "\r" not in old_string:
            old_string = self._with_crlf(old_string)
            new_string = self._with_crlf(new_string)
            occurrences = text.count(old_string)

        if occurrences == 0:
            raise WorkspaceFileError(f"old_string was not found in {path}. Read the file first and copy the text exactly, including whitespace.")

        if occurrences > 1 and not should_replace_all:
            raise WorkspaceFileError(f"old_string occurs {occurrences} times in {path}. Add surrounding text to make it unique, or pass replace_all=true to replace every occurrence.")

        replacement_count = occurrences if should_replace_all else 1
        updated_size = original_size + replacement_count * (len(new_string.encode(encoding)) - len(old_string.encode(encoding)))
        if updated_size > FILE_EDIT_MAX_BYTES:
            raise WorkspaceFileError(f"The edit would grow {path} to {updated_size // BYTES_PER_MIB} MiB, above the limit of {FILE_EDIT_MAX_BYTES // BYTES_PER_MIB} MiB. Replace fewer occurrences, use a shorter new_string, or use shell_execute.")

        updated = text.replace(old_string, new_string, replacement_count).encode(encoding)
        replace_file(relative_path, updated, path)
        return FileEditResult(path=str(target), replacements=replacement_count)

    @staticmethod
    def _with_crlf(value: str) -> str:
        return value if "\r" in value else value.replace("\n", "\r\n")

    @staticmethod
    def _text_codec_name(encoding: str) -> str:
        try:
            codec_info = codecs.lookup(encoding)
        except LookupError as error:
            raise WorkspaceFileError(f"Unknown encoding {encoding!r}. Pass a Python codec name, such as utf-8, utf-16 or cp1251.") from error

        if not getattr(codec_info, "_is_text_encoding", True):
            raise WorkspaceFileError(f"Encoding {encoding!r} is a byte transform, not a text codec. Pass a text codec, such as utf-8, utf-16 or cp1251.")

        return codec_info.name
