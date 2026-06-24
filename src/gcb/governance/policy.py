from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PrincipalContext:
    human_id: str
    agent_id: str
    roles: tuple[str, ...] = ("operator",)

    @classmethod
    def local_default(cls) -> PrincipalContext:
        return cls(human_id="local-human", agent_id="local-agent")
