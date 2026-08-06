from __future__ import annotations

from dataclasses import dataclass

from examtwin.assessment.answering_agent.contracts import AnswerTask


@dataclass(frozen=True)
class AgentBudget:
    max_iterations: int
    max_tool_calls: int


def budget_for_task(
    task: AnswerTask,
    *,
    iteration_cap: int,
    tool_call_cap: int,
    mandatory_tool_count: int,
) -> AgentBudget:
    """Allocate bounded headroom from task complexity without weakening hard caps."""

    subpart_count = max(1, len(task.question_spec.subparts))
    visual_count = len(task.question_spec.required_tool_names)
    desired_calls = 4 + mandatory_tool_count + min(subpart_count, 5) + visual_count
    tool_calls = min(tool_call_cap, max(mandatory_tool_count, desired_calls))
    iterations = min(iteration_cap, max(tool_calls + 3, 6))
    return AgentBudget(max_iterations=iterations, max_tool_calls=tool_calls)
