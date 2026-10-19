import os
import signal
import sys
import time
from typing import Final

from sandbox_scripts.proc_stat import SESSION_FIELD, START_TICKS_FIELD, STATE_FIELD, ZOMBIE_STATE, parse_stat_fields


MARKER_VARIABLE: Final[str] = "__LP_EXEC_ID"
MAX_PASSES: Final[int] = 200
SETTLE_SECONDS: Final[float] = 1.0
_PASS_INTERVAL_SECONDS: Final[float] = 0.05


def read_stat_fields(pid: str) -> list[str]:
    with open(f"/proc/{pid}/stat") as stat_file:
        return parse_stat_fields(stat_file.read())


def has_group_tag(pid: str, group_tag: str) -> bool:
    with open(f"/proc/{pid}/status") as status_file:
        for line in status_file:
            if line.startswith("Groups:"):
                return group_tag in line.split()[1:]

    return False


def has_marker(pid: str, marker: bytes) -> bool:
    with open(f"/proc/{pid}/environ", "rb") as environ_file:
        return marker in environ_file.read().split(b"\0")


def main() -> None:
    leader, ticks = int(sys.argv[1]), int(sys.argv[2])
    marker = f"{MARKER_VARIABLE}=".encode() + sys.argv[3].encode()
    group_tag = sys.argv[4]

    try:
        is_leader_verified = leader > 0 and int(read_stat_fields(str(leader))[START_TICKS_FIELD]) == ticks
    except (OSError, IndexError, ValueError):
        is_leader_verified = False

    def is_target(pid: str, stat_fields: list[str]) -> bool:
        if stat_fields[STATE_FIELD] == ZOMBIE_STATE or int(stat_fields[START_TICKS_FIELD]) < ticks:
            return False

        if is_leader_verified and int(stat_fields[SESSION_FIELD]) == leader:
            return True

        return has_group_tag(pid, group_tag) or has_marker(pid, marker)

    deadline = time.monotonic() + (SETTLE_SECONDS if leader == 0 else 0)
    own_pid = os.getpid()
    for _ in range(MAX_PASSES):
        has_killed = False
        for entry in os.listdir("/proc"):
            if not entry.isdigit() or int(entry) == own_pid:
                continue

            try:
                if is_target(entry, read_stat_fields(entry)):
                    os.kill(int(entry), signal.SIGKILL)
                    has_killed = True
            except (OSError, IndexError, ValueError):
                continue

        if not has_killed:
            if time.monotonic() >= deadline:
                sys.exit(0)

            time.sleep(_PASS_INTERVAL_SECONDS)

    sys.exit(1)


if __name__ == "__main__":
    main()
