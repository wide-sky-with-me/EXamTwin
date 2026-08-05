from __future__ import annotations

import re

from examtwin.answering_agent.contracts import (
    AnswerTask,
    required_answer_artifacts_are_present,
)
from examtwin.answering_agent.skills import mathematics_source_plot_overlay_mode
from examtwin.schemas.evidence import AnswerDiagram, AnswerImage


def _label_is_present(answer: str, label: str) -> bool:
    normalized = label.strip()
    if not normalized:
        return True
    escaped = re.escape(normalized)
    return bool(re.search(rf"(?im)(?:^|\s|[*_#]){escaped}(?=\s|[*_:.)]|$)", answer))


def verify_answer_contract(
    task: AnswerTask,
    answer_markdown: str,
    diagrams: tuple[AnswerDiagram, ...] | list[AnswerDiagram],
    images: tuple[AnswerImage, ...] | list[AnswerImage],
) -> None:
    required_tools = task.question_spec.required_tool_names
    if not required_answer_artifacts_are_present(diagrams, images, required_tools):
        produced = {diagram.tool_name for diagram in diagrams} | {
            image.tool_name for image in images
        }
        missing = sorted(set(required_tools) - produced)
        raise RuntimeError("answer is missing required visual artifacts: " + ", ".join(missing))

    overlay_mode = (
        mathematics_source_plot_overlay_mode(task.question) if task.subject_code == "9660" else None
    )
    if overlay_mode == "existing_curve_grid" and not any(
        diagram.tool_name == "math_plot" and diagram.source is not None for diagram in diagrams
    ):
        raise RuntimeError(
            "answer drawing on an existing curve/grid must be calibrated to the "
            "supplied original-paper figure"
        )

    labels = task.question_spec.labelled_subparts
    if len(labels) < 2:
        return
    missing_labels = [label for label in labels if not _label_is_present(answer_markdown, label)]
    if missing_labels:
        raise RuntimeError("answer is missing required subparts: " + ", ".join(missing_labels))
