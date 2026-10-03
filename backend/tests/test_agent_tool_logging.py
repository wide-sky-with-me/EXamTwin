import asyncio
import logging
from collections.abc import Mapping
from typing import Any, cast

import pytest
from examtwin.platform.agent_runtime.tools import (
    HarnessTool,
    PreparedToolCall,
    ToolCallResult,
    ToolExecutor,
)


class _FailingTool:
    async def invoke(self, arguments: Mapping[str, Any]) -> ToolCallResult:
        raise ValueError(f"invalid curve expression: {arguments['expression']}")


class _Lifecycle:
    result: ToolCallResult | None = None

    def replay(self, call: PreparedToolCall) -> ToolCallResult | None:
        return None

    def started(self, call: PreparedToolCall) -> None:
        return None

    def finished(self, call: PreparedToolCall, result: ToolCallResult) -> None:
        self.result = result


def test_tool_failure_logs_error_type_without_input_derived_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    call = PreparedToolCall.from_input("math_plot", {"expression": "exam-secret-curve"})
    lifecycle = _Lifecycle()

    with caplog.at_level(logging.WARNING, logger="examtwin.platform.agent_runtime.tools"):
        result = asyncio.run(
            ToolExecutor().execute(call, cast(HarnessTool, _FailingTool()), lifecycle)
        )

    assert result.is_error
    assert "exam-secret-curve" in result.content
    assert "answering_tool_failed tool_name=math_plot error_type=ValueError" in caplog.text
    assert "exam-secret-curve" not in caplog.text
