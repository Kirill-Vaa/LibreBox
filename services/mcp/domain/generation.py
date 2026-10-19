from dataclasses import dataclass


@dataclass(frozen=True)
class SandboxGeneration:
    container_id: str
    started_at: str
