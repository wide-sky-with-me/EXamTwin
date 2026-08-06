from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

from examtwin.platform.agent_runtime.model import HarnessMessage

StructuredResultT = TypeVar("StructuredResultT", bound=BaseModel)


class StructuredModelPort(Protocol):
    """Provider-neutral synchronous structured-output boundary."""

    @property
    def model_name(self) -> str: ...

    def complete(
        self,
        messages: Sequence[HarnessMessage],
        response_model: type[StructuredResultT],
        *,
        timeout: float,
    ) -> StructuredResultT: ...


@dataclass(frozen=True)
class StructuredTask:
    system_prompt: str
    user_content: str

    def messages(self) -> tuple[HarnessMessage, HarnessMessage]:
        if not self.system_prompt.strip():
            raise ValueError("structured task system prompt cannot be empty")
        if not self.user_content.strip():
            raise ValueError("structured task user content cannot be empty")
        return (
            HarnessMessage(role="system", content=self.system_prompt.strip()),
            HarnessMessage(role="user", content=self.user_content.strip()),
        )


class StructuredTaskRunner(Generic[StructuredResultT]):
    """Run one schema-constrained model task through a replaceable model port."""

    def __init__(self, model: StructuredModelPort) -> None:
        self.model = model

    def run(
        self,
        task: StructuredTask,
        response_model: type[StructuredResultT],
        *,
        timeout: float,
    ) -> StructuredResultT:
        if timeout <= 0:
            raise ValueError("structured task timeout must be positive")
        result = self.model.complete(task.messages(), response_model, timeout=timeout)
        if not isinstance(result, response_model):
            raise TypeError("structured model returned the wrong response type")
        return result
