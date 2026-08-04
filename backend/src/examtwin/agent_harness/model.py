from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

MessageRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class HarnessMessage:
    """Provider-neutral text message at the harness boundary."""

    role: MessageRole
    content: str


class ChatModelPort(Protocol):
    """Minimal model surface required by an iterative harness."""

    @property
    def model_name(self) -> str: ...

    async def complete(self, messages: Sequence[HarnessMessage]) -> str: ...
