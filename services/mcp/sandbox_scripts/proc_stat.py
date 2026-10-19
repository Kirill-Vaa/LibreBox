from typing import Final


STATE_FIELD: Final[int] = 0
PROCESS_GROUP_FIELD: Final[int] = 2
SESSION_FIELD: Final[int] = 3
START_TICKS_FIELD: Final[int] = 19
ZOMBIE_STATE: Final[str] = "Z"


def parse_stat_fields(stat_text: str) -> list[str]:
    return stat_text.rsplit(")", 1)[1].split()
