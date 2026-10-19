import re
from pathlib import Path
from typing import Final


_SCRIPTS_DIRECTORY: Final[Path] = Path(__file__).parent
_SHARED_IMPORT_PATTERN: Final[re.Pattern[str]] = re.compile(r"^from sandbox_scripts\.(\w+) import [^\n]*$", re.MULTILINE)


def _inline_shared_modules(module_name: str, bundled_names: set[str]) -> str:
    def inline(match: re.Match[str]) -> str:
        shared_name = match.group(1)
        if shared_name in bundled_names:
            return ""

        bundled_names.add(shared_name)
        return _inline_shared_modules(shared_name, bundled_names)

    return _SHARED_IMPORT_PATTERN.sub(inline, (_SCRIPTS_DIRECTORY / f"{module_name}.py").read_text())


def _load(module_name: str) -> str:
    return _inline_shared_modules(module_name, {module_name})


EXEC_KILL_SCRIPT: Final[str] = _load("exec_kill")
IDENTITY_SCRIPT: Final[str] = _load("identity")
METADATA_SCAN_SCRIPT: Final[str] = _load("metadata_scan")
METADATA_WRITE_SCRIPT: Final[str] = _load("metadata_write")
PROBE_SCRIPT: Final[str] = _load("probe")
RECORD_EXIT_SCRIPT: Final[str] = _load("record_exit")
SIGNAL_SCRIPT: Final[str] = _load("signal_group")
TAIL_CHUNK_SCRIPT: Final[str] = _load("tail_chunk")
TAIL_LINES_SCRIPT: Final[str] = _load("tail_lines")
