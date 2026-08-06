from __future__ import annotations

import re

from examtwin.assessment.answering_agent.contracts import AnswerTask, SubjectSkill
from examtwin.assessment.answering_agent.run_policy import required_artifact_tools

_CONDITIONAL_TOOLS = frozenset(
    {
        "question_vision",
        "paired_exam_lookup",
        "math_plot",
        "math_diagram",
        "economics_diagram",
        "image_generate",
    }
)

_PAIRED_CONTEXT_REFERENCE = re.compile(
    r"\b(?:extract\s+[a-z0-9]+|source\s+booklet|insert)\b",
    re.IGNORECASE,
)


def select_answering_tool_names(
    skill: SubjectSkill,
    task: AnswerTask,
) -> tuple[str, ...]:
    """Select the smallest deterministic tool surface justified before a run."""

    selected = set(skill.tool_names) - _CONDITIONAL_TOOLS
    selected.update(skill.required_tool_names)
    selected.update(skill.mandatory_tool_names)
    selected.update(required_artifact_tools(skill, task))
    if task.question_images:
        selected.add("question_vision")
    if task.pair_key and _PAIRED_CONTEXT_REFERENCE.search(task.question):
        selected.add("paired_exam_lookup")
    return tuple(name for name in skill.tool_names if name in selected)
