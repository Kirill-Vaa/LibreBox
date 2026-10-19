import os
import stat
import time
from collections.abc import Iterator
from pathlib import PurePosixPath

from domain.exceptions import SandboxError, WorkspaceFileError
from domain.models import DirectoryTreeResult, TreeNode
from domain.workspace import resolve_workspace_path, to_workspace_relative
from infrastructure.fs.beneath import open_beneath, open_beneath_fd, open_directory_beneath_fd, open_workspace_root
from services.file_constants import FILE_TREE_MAX_NODES, FILE_TREE_TIMEOUT_SECONDS
from services.file_operations import run_file_operation, to_display_name
from utils.logger import logger


class _NodeBudget:
    def __init__(self, max_nodes: int) -> None:
        self._remaining = max_nodes
        self.is_exhausted = False

    def take(self) -> bool:
        if self._remaining <= 0:
            self.is_exhausted = True
            return False

        self._remaining -= 1
        return True


async def build_directory_tree(path: str, max_depth: int, should_show_hidden: bool, should_show_sizes: bool) -> DirectoryTreeResult:
    target = resolve_workspace_path(path)
    root_node, is_truncated = await run_file_operation(path, walk_directory_tree, target, path, max_depth, should_show_hidden, should_show_sizes)
    if is_truncated:
        logger.info(f"Directory tree for {path} was cut at the {FILE_TREE_MAX_NODES} node limit")

    return DirectoryTreeResult(root=root_node, truncated=is_truncated)


def walk_directory_tree(target: PurePosixPath, path: str, max_depth: int, should_show_hidden: bool, should_show_sizes: bool) -> tuple[TreeNode, bool]:
    relative_path = to_workspace_relative(target)
    deadline = time.monotonic() + FILE_TREE_TIMEOUT_SECONDS
    budget = _NodeBudget(FILE_TREE_MAX_NODES)

    with open_workspace_root() as root_fd:
        try:
            directory_fd = open_directory_beneath_fd(root_fd, relative_path, path)
        except NotADirectoryError:
            with open_beneath(relative_path, os.O_RDONLY, path) as file_descriptor:
                size_bytes = os.fstat(file_descriptor).st_size if should_show_sizes else 0

            return TreeNode(name=target.name, path=str(target), is_dir=False, size_bytes=size_bytes, children=[]), False

        try:
            root_node = _build_node(directory_fd, target, max_depth, should_show_hidden, should_show_sizes, deadline, budget)
            return root_node, budget.is_exhausted
        finally:
            os.close(directory_fd)


def _build_node(directory_fd: int, target: PurePosixPath, depth_remaining: int, should_show_hidden: bool, should_show_sizes: bool, deadline: float, budget: _NodeBudget) -> TreeNode:
    entries: list[tuple[bool, str, os.stat_result]] = []
    for name in os.listdir(directory_fd):
        if not should_show_hidden and name.startswith("."):
            continue

        _check_tree_deadline(deadline)
        try:
            entry_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError as error:
            logger.debug(f"Skipped unreadable tree entry {target / to_display_name(name)}: {error}")
            continue

        entries.append((stat.S_ISDIR(entry_stat.st_mode), name, entry_stat))

    children: list[TreeNode] = []
    total_bytes = 0
    for is_directory, name, entry_stat in sorted(entries, key=lambda entry: (not entry[0], entry[1].lower())):
        display_name = to_display_name(name)
        entry_path = target / display_name

        if not is_directory:
            size_bytes = entry_stat.st_size if should_show_sizes else 0
            total_bytes += size_bytes
            if depth_remaining > 0 and budget.take():
                children.append(TreeNode(name=display_name, path=str(entry_path), is_dir=False, size_bytes=size_bytes, children=[]))
            continue

        if depth_remaining == 0 and not should_show_sizes:
            continue

        try:
            child_fd = _open_child_directory(directory_fd, name, str(entry_path))
        except (OSError, SandboxError) as error:
            logger.debug(f"Skipped unreadable tree directory {entry_path}: {error}")
            continue

        try:
            if depth_remaining > 0 and budget.take():
                child = _build_node(child_fd, entry_path, depth_remaining - 1, should_show_hidden, should_show_sizes, deadline, budget)
                children.append(child)
                total_bytes += child.size_bytes
            else:
                total_bytes += _directory_size(child_fd, should_show_hidden, deadline)
        finally:
            os.close(child_fd)

    return TreeNode(name=target.name, path=str(target), is_dir=True, size_bytes=total_bytes, children=children)


def _directory_size(directory_fd: int, should_show_hidden: bool, deadline: float) -> int:
    total_bytes = 0
    stack: list[tuple[int, Iterator[str]]] = []
    try:
        _push_directory(stack, os.dup(directory_fd))
        while stack:
            _check_tree_deadline(deadline)
            current_fd, names = stack[-1]
            name = next(names, None)
            if name is None:
                stack.pop()
                os.close(current_fd)
                continue

            if not should_show_hidden and name.startswith("."):
                continue

            try:
                entry_stat = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
            except OSError:
                continue

            if not stat.S_ISDIR(entry_stat.st_mode):
                total_bytes += entry_stat.st_size
                continue

            try:
                child_fd = _open_child_directory(current_fd, name, name)
            except (OSError, SandboxError):
                continue

            _push_directory(stack, child_fd)
    finally:
        for open_fd, _ in stack:
            os.close(open_fd)

    return total_bytes


def _open_child_directory(parent_fd: int, name: str, display_path: str) -> int:
    return open_beneath_fd(parent_fd, name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, display_path)


def _push_directory(stack: list[tuple[int, Iterator[str]]], directory_fd: int) -> None:
    try:
        names = os.listdir(directory_fd)
    except OSError:
        os.close(directory_fd)
        return
    except BaseException:
        os.close(directory_fd)
        raise

    stack.append((directory_fd, iter(names)))


def _check_tree_deadline(deadline: float) -> None:
    if time.monotonic() > deadline:
        raise WorkspaceFileError(f"Walking the directory took longer than {FILE_TREE_TIMEOUT_SECONDS} s and was stopped. Lower max_depth, pass show_sizes=false, or use a narrower path.")
