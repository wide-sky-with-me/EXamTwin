"""Compile the same frozen execution scope for durable workers and offline experiments."""

from __future__ import annotations

import json
from typing import Any

from examtwin.assessment.strategy import question_strategy
from examtwin.contracts.strategy import StrategyPlan


def apply_question_strategy(
    plan: StrategyPlan, item: dict[str, Any], parts: list[dict[str, Any]]
) -> dict[str, Any] | None:
    options = question_strategy(plan, item["number"])
    if not options:
        return None
    if any(o.mode == "partial" and not o.stop_before.strip() for o in options):
        raise ValueError("旧版部分作答策略缺少明确停止边界；请新建任务，禁止静默重规划")
    labels = {o.subpart for o in options}
    selected_parts = [dict(p) for p in parts if p["label"] in labels]
    without_artifacts = {o.subpart for o in options if not o.includes_required_artifact}
    for part in selected_parts:
        if part["label"] in without_artifacts:
            part["required_tool"] = None
            part["answer_kind"] = "text"
    result = dict(item)
    by_code = {s.code: s for s in plan.analysis.skills}
    needed = {code for o in options for code in o.skills}
    pending = list(needed)
    while pending:
        for prerequisite in by_code[pending.pop()].prerequisites:
            if prerequisite not in needed:
                needed.add(prerequisite)
                pending.append(prerequisite)
    result["requirements_json"] = json.dumps(
        {"subparts": selected_parts, "total_marks": sum(p["marks"] for p in selected_parts)}
    )
    result["strategy_instruction"] = json.dumps(
        {
            "skipped_subparts": [p["label"] for p in parts if p["label"] not in labels],
            "approaches": [
                {
                    "subpart": o.subpart,
                    "mode": o.mode,
                    "approach": o.approach,
                    "stop_before": o.stop_before,
                    "exam_minutes": o.exam_minutes,
                }
                for o in options
            ],
            "learning_scope": [s.model_dump() for s in plan.analysis.skills if s.code in needed],
        },
        ensure_ascii=False,
    )
    return result
