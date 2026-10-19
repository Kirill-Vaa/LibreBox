from typing import Annotated

from mcp.server.mcpserver import Image, MCPServer
from pydantic import Field

from config.constants import BYTES_PER_MIB, WORKSPACE_PATH
from domain.models import DirectoryResult, DirectoryTreeResult, FileEditResult, FileReadResult, FileSearchMode, FileSearchResult, FileWriteResult
from mcp_server.constants import MCP_MAX_REQUEST_BODY_BYTES, TOOL_ENCODING_MAX_CHARS
from mcp_server.descriptions import DIRECTORY_PATH_DESCRIPTION, ENCODING_EXAMPLES, FILE_PATH_DESCRIPTION
from services.file_constants import FILE_EDIT_MAX_BYTES, FILE_READ_BINARY_SNIFF_BYTES, FILE_READ_DEFAULT_LIMIT, FILE_READ_MAX_BYTES, FILE_READ_MAX_CONTENT_CHARS, FILE_READ_MAX_LINES, FILE_SEARCH_DEFAULT_MAX_RESULTS, FILE_SEARCH_MAX_COLUMNS, FILE_SEARCH_MAX_RESULTS, FILE_SEARCH_PATTERN_MAX_CHARS, FILE_SEARCH_TIMEOUT_SECONDS, FILE_TREE_DEFAULT_DEPTH, FILE_TREE_MAX_DEPTH, FILE_TREE_MAX_NODES, FILE_TREE_TIMEOUT_SECONDS
from services.file_service import FileService
from services.image_constants import FILE_VIEW_IMAGE_MAX_BASE64_BYTES, FILE_VIEW_IMAGE_MAX_DIMENSION, FILE_VIEW_IMAGE_MAX_INPUT_BYTES, FILE_VIEW_IMAGE_MAX_PIXELS, FILE_VIEW_IMAGE_MIN_DIMENSION
from services.image_view_service import ImageViewService


def register_file_tools(mcp: MCPServer, file_service: FileService, image_view_service: ImageViewService) -> None:

    @mcp.tool(
        description=(
            f"Read a text file in {WORKSPACE_PATH}. "
            "Each line comes back as its 1-based number, a tab and the text, with line endings removed. "
            "To page through a long file, pass offset. line_count is the total number of lines in the file. "
            f"One call returns at most {FILE_READ_MAX_CONTENT_CHARS} characters, whatever limit says. If truncated is true, call again with offset=next_offset. "
            "A single line longer than that is cut and ends with a [... N chars truncated ...] marker. The marker is not file content. offset counts whole lines, so read the rest of such a line with shell_execute, for example with cut -c or sed. "
            f"Files above {FILE_READ_MAX_BYTES // BYTES_PER_MIB} MiB are refused. Read those in parts with shell_execute. "
            f"If a file has a NUL byte in its first {FILE_READ_BINARY_SNIFF_BYTES // 1024} KiB, it is treated as binary: is_binary is true and content is empty. This check is skipped for UTF-16 and UTF-32. "
            "For images use file_view_image."
        )
    )
    async def file_read(
        path: Annotated[str, Field(description=FILE_PATH_DESCRIPTION)],
        offset: Annotated[int, Field(description="Number of lines to skip from the start of the file. Minimum: 0. Default: 0.", ge=0)] = 0,
        limit: Annotated[int, Field(description=f"Maximum number of lines to return. Range: 1-{FILE_READ_MAX_LINES}. Default: {FILE_READ_DEFAULT_LIMIT}.", ge=1, le=FILE_READ_MAX_LINES)] = FILE_READ_DEFAULT_LIMIT,
        encoding: Annotated[str, Field(description=f"{ENCODING_EXAMPLES} Bytes that do not decode become U+FFFD. Default: utf-8.", max_length=TOOL_ENCODING_MAX_CHARS)] = "utf-8",
    ) -> FileReadResult:
        return await file_service.read(path=path, offset=offset, limit=limit, encoding=encoding)

    @mcp.tool(
        description=(
            f"Show an image from {WORKSPACE_PATH} so that you can see it, for example a browser screenshot. Returns the image and a text note with its size and scale. "
            "PNG, JPEG, WebP and GIF are supported. The format is detected from the content, not the file extension. For an animated GIF only the first frame is shown. "
            f"An image longer than max_dimension, or larger than {FILE_VIEW_IMAGE_MAX_BASE64_BYTES // 1_000_000} MB after base64 encoding, is shrunk automatically. A full-page screenshot is an example. The file itself is never changed. "
            "To read small text in a large image, view it whole first, then pass region, in original pixels, to see that part at full resolution. "
            f"Files above {FILE_VIEW_IMAGE_MAX_INPUT_BYTES // BYTES_PER_MIB} MiB or {FILE_VIEW_IMAGE_MAX_PIXELS // 1_000_000} megapixels are refused. Shrink or crop those with shell_execute first."
        )
    )
    async def file_view_image(
        path: Annotated[str, Field(description=FILE_PATH_DESCRIPTION)],
        region: Annotated[list[Annotated[int, Field(ge=0)]] | None, Field(description="Part of the image to show, as [x, y, width, height] in pixels of the upright original, as given in the note. x and y are the top-left corner. A region that reaches past the image edge is cut off. Default: the whole image.", min_length=4, max_length=4)] = None,
        max_dimension: Annotated[int, Field(description=f"Longest side, in pixels, of the image you are shown. Lower it to save tokens when detail does not matter. Range: {FILE_VIEW_IMAGE_MIN_DIMENSION}-{FILE_VIEW_IMAGE_MAX_DIMENSION}. Default: {FILE_VIEW_IMAGE_MAX_DIMENSION}.", ge=FILE_VIEW_IMAGE_MIN_DIMENSION, le=FILE_VIEW_IMAGE_MAX_DIMENSION)] = FILE_VIEW_IMAGE_MAX_DIMENSION,
    ) -> list[Image | str]:
        return await image_view_service.view(path=path, max_dimension=max_dimension, region=region)

    @mcp.tool(
        description=(
            f"Create a text file in {WORKSPACE_PATH}, or overwrite it, with the given content. "
            "Writing through a symlink is refused. For binary data use shell_execute. "
            f"One tool call carries at most {MCP_MAX_REQUEST_BODY_BYTES // BYTES_PER_MIB} MiB of JSON. Build larger files in parts, for example by appending with shell_execute."
        )
    )
    async def file_write(
        path: Annotated[str, Field(description=FILE_PATH_DESCRIPTION)],
        content: Annotated[str, Field(description="Complete new content of the file.")],
        create_dirs: Annotated[bool, Field(description="Create missing parent directories. Default: true.")] = True,
        encoding: Annotated[str, Field(description=f"{ENCODING_EXAMPLES} Default: utf-8.", max_length=TOOL_ENCODING_MAX_CHARS)] = "utf-8",
    ) -> FileWriteResult:
        return await file_service.write(path=path, content=content, should_create_dirs=create_dirs, encoding=encoding)

    @mcp.tool(
        description=(
            f"Replace exact text in an existing text file in {WORKSPACE_PATH}. The rest of the file, including its line endings, stays unchanged. "
            "Matching is literal, not regex, and whitespace must match exactly. Read the file first and copy the text from it. "
            "In a file with CRLF line endings, a multi-line old_string written with plain newlines still matches, and new_string is written with CRLF. "
            "By default old_string must occur exactly once, so include enough surrounding text to make it unique. To replace every occurrence, set replace_all. "
            "The file is refused if decoding and re-encoding it with the chosen encoding would change its bytes. For example, a UTF-16 file with a big-endian BOM under utf-16 is refused. Name the exact codec instead, such as utf-16-be. "
            f"Files above {FILE_EDIT_MAX_BYTES // BYTES_PER_MIB} MiB are refused. Edit those with sed or a script via shell_execute."
        )
    )
    async def file_edit(
        path: Annotated[str, Field(description=FILE_PATH_DESCRIPTION)],
        old_string: Annotated[str, Field(description="Exact text to replace. It must not be empty.")],
        new_string: Annotated[str, Field(description="Replacement text. Empty deletes old_string.")],
        replace_all: Annotated[bool, Field(description="Replace every occurrence instead of requiring exactly one. Default: false.")] = False,
        encoding: Annotated[str, Field(description=f"{ENCODING_EXAMPLES} The whole file must decode without errors. Default: utf-8.", max_length=TOOL_ENCODING_MAX_CHARS)] = "utf-8",
    ) -> FileEditResult:
        return await file_service.edit(path=path, old_string=old_string, new_string=new_string, should_replace_all=replace_all, encoding=encoding)

    @mcp.tool(
        description=(
            f"Search {WORKSPACE_PATH} in one of two modes. "
            "content mode runs ripgrep. pattern is a regex matched inside files, case-sensitive. Each match is returned as absolute_path:line:text. "
            f"Lines longer than {FILE_SEARCH_MAX_COLUMNS} bytes are shortened to a preview. Hidden files, files listed in .ignore and, inside a git repository, files ignored by .gitignore are skipped, and so are binary files. "
            "files mode runs fd. pattern is a glob matched against file and directory names only, not paths, so it cannot contain /. It is case-insensitive if pattern is all lowercase, otherwise case-sensitive. Hidden and ignored files are included. "
            f"If truncated is true, more results exist beyond max_results. Narrow pattern, path or glob. The search stops after {FILE_SEARCH_TIMEOUT_SECONDS} s with timed_out=true and partial results."
        )
    )
    async def file_search(
        pattern: Annotated[str, Field(description="Content mode: regex matched inside files. Files mode: glob matched against names, such as *.csv.", max_length=FILE_SEARCH_PATTERN_MAX_CHARS)],
        path: Annotated[str, Field(description=f"{DIRECTORY_PATH_DESCRIPTION} The search covers it and everything below it. Default: . (the workspace root).")] = ".",
        glob: Annotated[str | None, Field(description="Content mode only: glob on file paths that keeps matching files or, with a leading !, excludes them, such as *.py or !*.min.js. Ignored in files mode. Default: no filter.", max_length=FILE_SEARCH_PATTERN_MAX_CHARS)] = None,
        mode: Annotated[FileSearchMode, Field(description="content to search inside files, or files to find files and directories by name. Default: content.")] = "content",
        max_results: Annotated[int, Field(description=f"Maximum number of matching lines or paths to return. Range: 1-{FILE_SEARCH_MAX_RESULTS}. Default: {FILE_SEARCH_DEFAULT_MAX_RESULTS}.", ge=1, le=FILE_SEARCH_MAX_RESULTS)] = FILE_SEARCH_DEFAULT_MAX_RESULTS,
    ) -> FileSearchResult:
        return await file_service.search(pattern=pattern, path=path, glob=glob, mode=mode, max_results=max_results)

    @mcp.tool(
        description=(
            f"Create a directory in {WORKSPACE_PATH}. Succeeds if the directory already exists."
        )
    )
    async def directory_create(
        path: Annotated[str, Field(description=DIRECTORY_PATH_DESCRIPTION)],
        parents: Annotated[bool, Field(description="Create missing parent directories. If false, a missing parent is an error. Default: true.")] = True,
    ) -> DirectoryResult:
        return await file_service.create_directory(path=path, should_create_parents=parents)

    @mcp.tool(
        description=(
            f"List the tree of a directory in {WORKSPACE_PATH} down to max_depth, with file sizes and total sizes for directories. Symlinks are listed but not followed. "
            f"At most {FILE_TREE_MAX_NODES} entries are returned. If truncated is true, the rest were left out, so on large or unfamiliar directories such as node_modules or a virtualenv start with max_depth 1 or 2, "
            "and find individual files with file_search in files mode. Directory sizes stay complete even where entries were left out. "
            f"The walk fails after {FILE_TREE_TIMEOUT_SECONDS} s. Then lower max_depth, pass show_sizes=false or use a narrower path."
        )
    )
    async def directory_tree(
        path: Annotated[str, Field(description=f"{DIRECTORY_PATH_DESCRIPTION} A file path returns that single entry. Default: . (the workspace root).")] = ".",
        max_depth: Annotated[int, Field(description=f"Number of levels to list below path. 0 returns only the directory itself. Range: 0-{FILE_TREE_MAX_DEPTH}. Default: {FILE_TREE_DEFAULT_DEPTH}.", ge=0, le=FILE_TREE_MAX_DEPTH)] = FILE_TREE_DEFAULT_DEPTH,
        show_hidden: Annotated[bool, Field(description="Include entries whose names start with a dot, such as .git. Without it, hidden entries are also left out of directory sizes. Default: false.")] = False,
        show_sizes: Annotated[bool, Field(description="Compute file and directory sizes. Turn it off to speed up large trees, then every size is 0. Default: true.")] = True,
    ) -> DirectoryTreeResult:
        return await file_service.tree(path=path, max_depth=max_depth, should_show_hidden=show_hidden, should_show_sizes=show_sizes)
