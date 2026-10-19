import json
import os
import sys
import time
from string import ascii_lowercase, digits
from typing import Any, Final

from sandbox_scripts.file_access import open_regular


PROCESS_ID_CHARACTERS: Final[frozenset[str]] = frozenset(ascii_lowercase + digits)
SKIP_REASON_MAX_CHARS: Final[int] = 500


def list_names(directory: str, cursor: str, skipped: list[str]) -> list[str]:
    try:
        return sorted(name for name in os.listdir(directory) if name > cursor and name.endswith(".json"))
    except FileNotFoundError:
        return []
    except OSError as error:
        skipped.append(f"{directory}: {error.strerror}")
        return []


def read_metadata(directory: str, name: str, max_bytes: int) -> dict[str, Any]:
    descriptor = open_regular(os.path.join(directory, name))
    try:
        if os.fstat(descriptor).st_size > max_bytes:
            raise ValueError(f"larger than {max_bytes} bytes")

        metadata = json.loads(os.pread(descriptor, max_bytes, 0))
    finally:
        os.close(descriptor)

    if not isinstance(metadata, dict):
        raise ValueError("not a JSON object")

    return metadata


def is_process_id_file(name: str, process_id: str, process_id_length: int) -> bool:
    return name.endswith(".json") and len(process_id) == process_id_length and set(process_id) <= PROCESS_ID_CHARACTERS


def main() -> None:
    directory, container_id, started_at = sys.argv[1], sys.argv[2], sys.argv[3]
    process_id_length, max_bytes = int(sys.argv[4]), int(sys.argv[5])
    cursor, page_chars, page_seconds = sys.argv[6], int(sys.argv[7]), float(sys.argv[8])

    deadline = time.monotonic() + page_seconds
    records: list[dict[str, Any]] = []
    skipped: list[str] = []
    used_chars = 0
    next_cursor: str | None = None

    for name in list_names(directory, cursor, skipped):
        if next_cursor is not None and (used_chars >= page_chars or time.monotonic() >= deadline):
            break

        next_cursor = name
        process_id = name.removesuffix(".json")
        if not is_process_id_file(name, process_id, process_id_length):
            continue

        try:
            metadata = read_metadata(directory, name, max_bytes)
        except (OSError, ValueError, RecursionError) as error:
            reason = f"{name}: {getattr(error, 'strerror', None) or error}"[:SKIP_REASON_MAX_CHARS]
            skipped.append(reason)
            used_chars += len(reason)
            continue

        if metadata.get("container_id") == container_id and metadata.get("started_at") == started_at:
            record = {"process_id": process_id, "metadata": metadata}
            records.append(record)
            used_chars += len(json.dumps(record))
    else:
        next_cursor = None

    print(json.dumps({"records": records, "skipped": skipped, "next_cursor": next_cursor}))


if __name__ == "__main__":
    main()
