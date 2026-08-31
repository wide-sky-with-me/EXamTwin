from __future__ import annotations

import re

from examtwin.assessment.answering_agent.contracts import (
    AnswerTask,
    required_answer_artifacts_are_present,
)
from examtwin.contracts.evidence import AnswerDiagram, AnswerImage


def _label_is_present(answer: str, label: str) -> bool:
    normalized = label.strip()
    if not normalized:
        return True
    escaped = re.escape(normalized)
    # Decimal and parenthesized subparts are commonly rendered with the top-level
    # question number (``18.1`` / ``Q18(a)``), even though the trusted paper
    # contract stores only ``.1`` / ``(a)``.  Accept that presentation alias while
    # still requiring a label boundary; never equate differently numbered parts.
    question_prefix = r"(?:q(?:uestion)?\s*)?\d+\s*" if normalized[0] in ".(" else ""
    return bool(
        re.search(
            rf"(?im)(?:^|\s|[*_#])(?:{question_prefix})?{escaped}(?=\s|[*_:.)]|$)",
            answer,
        )
    )


def verify_answer_contract(
    task: AnswerTask,
    answer_markdown: str,
    diagrams: tuple[AnswerDiagram, ...] | list[AnswerDiagram],
    images: tuple[AnswerImage, ...] | list[AnswerImage],
    *,
    source_plot_overlay_mode: str | None = None,
) -> None:
    required_tools = task.question_spec.required_tool_names
    if not required_answer_artifacts_are_present(diagrams, images, required_tools):
        produced = {diagram.tool_name for diagram in diagrams} | {
            image.tool_name for image in images
        }
        missing = sorted(set(required_tools) - produced)
        raise RuntimeError("answer is missing required visual artifacts: " + ", ".join(missing))

    artifacts = [*diagrams, *images]
    artifact_ids = [artifact.artifact_id for artifact in artifacts if artifact.artifact_id]
    artifact_orders = [artifact.answer_order for artifact in artifacts if artifact.answer_order]
    if len(artifact_ids) != len(set(artifact_ids)):
        raise RuntimeError("answer contains duplicate artifact ids")
    if len(artifact_orders) != len(set(artifact_orders)):
        raise RuntimeError("answer contains duplicate artifact orders")

    labels = task.question_spec.labelled_subparts
    valid_anchors = set(labels) if labels else {"whole"}
    invalid_anchors = sorted(
        {
            artifact.answer_anchor
            for artifact in artifacts
            if artifact.answer_anchor is not None and artifact.answer_anchor not in valid_anchors
        }
    )
    if invalid_anchors:
        raise RuntimeError("answer artifacts have invalid anchors: " + ", ".join(invalid_anchors))

    # Artifacts created under the placement contract always carry all three metadata fields.
    # Legacy persisted answers carry none and remain readable through the frontend fallback.
    placed_artifacts = [artifact for artifact in artifacts if artifact.artifact_id is not None]
    if placed_artifacts and any(
        artifact.answer_anchor is None or artifact.answer_order is None for artifact in artifacts
    ):
        raise RuntimeError("answer mixes placed and unplaced artifacts")
    if placed_artifacts:
        missing_placements: list[str] = []
        for part in task.question_spec.subparts:
            if part.required_tool is None:
                continue
            anchor = part.label if part.label in labels else "whole"
            if not any(
                artifact.tool_name == part.required_tool and artifact.answer_anchor == anchor
                for artifact in artifacts
            ):
                missing_placements.append(f"{anchor}:{part.required_tool}")
        if missing_placements:
            raise RuntimeError(
                "answer is missing anchored visual artifacts: " + ", ".join(missing_placements)
            )

    overlay_mode = source_plot_overlay_mode
    if overlay_mode == "existing_curve_grid" and not any(
        diagram.tool_name == "math_plot" and diagram.source is not None for diagram in diagrams
    ):
        raise RuntimeError(
            "answer drawing on an existing curve/grid must be calibrated to the "
            "supplied original-paper figure"
        )

    if len(labels) < 2:
        return
    missing_labels = [label for label in labels if not _label_is_present(answer_markdown, label)]
    if missing_labels:
        raise RuntimeError("answer is missing required subparts: " + ", ".join(missing_labels))
