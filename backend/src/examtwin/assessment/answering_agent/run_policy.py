from __future__ import annotations

import re

from examtwin.assessment.answering_agent.contracts import AnswerTask, SubjectSkill

INSUFFICIENT_EVIDENCE = "当前知识库没有找到足够证据回答这个问题。"

TOOL_LABELS = {
    "question_vision": "核对原题页图",
    "knowledge_search": "检索知识库",
    "source_read": "读取参考原文",
    "paired_exam_lookup": "读取同卷材料",
    "math_calculate": "执行数学计算",
    "probability_calculate": "核验概率计算",
    "economics_calculate": "核验经济量化计算",
    "math_plot": "生成坐标图",
    "math_diagram": "生成答案图形",
    "economics_diagram": "生成经济学图形",
    "image_generate": "生成答案图片",
}

FINAL_ONLY_OBSERVATION = (
    "Tool use is no longer available. Return only `Answer:` followed by one JSON "
    "object containing answer_markdown, citation_ids, confidence, grounded, and warnings. "
    "Use the observations already available and do not include reasoning."
)
FORMAT_REPAIR_OBSERVATION = (
    "The previous response did not follow the required protocol. Return exactly one "
    "tool call, or `Answer:` followed by one valid final JSON object. Do not include "
    "hidden reasoning."
)

_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)


def required_artifact_tools(skill: SubjectSkill, task: AnswerTask) -> tuple[str, ...]:
    structured = task.question_spec.required_tool_names
    if structured or task.strategy_instruction:
        return structured
    fallback = skill.required_visual_tool(task.visual_request_text or task.question)
    return () if fallback is None else (fallback,)


def visible_model_output(text: str) -> str:
    """Remove hidden-reasoning tags before parsing or recovering visible output."""

    cleaned = _THINK_BLOCK.sub("", text)
    lowered = cleaned.lower()
    if "</think>" in lowered:
        closing = lowered.rfind("</think>")
        cleaned = cleaned[closing + len("</think>") :]
    lowered = cleaned.lower()
    if "<think" in lowered:
        opening = lowered.find("<think")
        cleaned = cleaned[:opening]
    return cleaned.strip()
