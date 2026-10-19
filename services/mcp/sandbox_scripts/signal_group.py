import os
import signal
import sys
from typing import Final

from sandbox_scripts.proc_stat import PROCESS_GROUP_FIELD, START_TICKS_FIELD, STATE_FIELD, ZOMBIE_STATE, parse_stat_fields


GONE_EXIT_CODE: Final[int] = 3
MEMBERS_ONLY_EXIT_CODE: Final[int] = 4
PROBE_SIGNAL_NAME: Final[str] = "PROBE"


def read_fields(pid: int) -> list[str]:
    try:
        with open(f"/proc/{pid}/stat") as stat_file:
            return parse_stat_fields(stat_file.read())
    except (OSError, IndexError):
        return []


def belongs_to_group(pid: int, leader: int, ticks: int) -> bool:
    fields = read_fields(pid)
    return bool(fields) and fields[STATE_FIELD] != ZOMBIE_STATE and int(fields[PROCESS_GROUP_FIELD]) == leader and int(fields[START_TICKS_FIELD]) >= ticks


def has_surviving_members(leader: int, ticks: int) -> bool:
    return any(belongs_to_group(int(entry), leader, ticks) for entry in os.listdir("/proc") if entry.isdigit() and int(entry) != leader)


def main() -> None:
    leader, ticks, name = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    leader_fields = read_fields(leader)
    if leader_fields and int(leader_fields[START_TICKS_FIELD]) != ticks:
        sys.exit(GONE_EXIT_CODE)

    is_leader_alive = bool(leader_fields) and leader_fields[STATE_FIELD] != ZOMBIE_STATE
    if not is_leader_alive and not has_surviving_members(leader, ticks):
        sys.exit(GONE_EXIT_CODE)

    try:
        os.killpg(leader, 0 if name == PROBE_SIGNAL_NAME else getattr(signal, f"SIG{name}"))
    except ProcessLookupError:
        sys.exit(GONE_EXIT_CODE)

    sys.exit(0 if is_leader_alive else MEMBERS_ONLY_EXIT_CODE)


if __name__ == "__main__":
    main()
