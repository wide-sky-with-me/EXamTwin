from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from examtwin.knowledge.curriculum import CurriculumCandidate
from examtwin.knowledge.difficulty import (
    EASY_DIFFICULTY_UPPER_BOUND,
    MEDIUM_DIFFICULTY_UPPER_BOUND,
)
from examtwin.platform.agent_runtime import (
    StructuredModelPort,
    StructuredTask,
    StructuredTaskRunner,
)
from examtwin.platform.config import Settings
from examtwin.platform.prompts import load_prompt_template
from examtwin.platform.structured_model import LiteLLMStructuredModel
from examtwin.subjects.public import SubjectPack

DIFFICULTY_METHOD = "model-evidence-direct-v1"
EVIDENCE_MATCHER_VERSION = "difficulty-evidence-bm25-v1"
_PROMPT_PATH = "difficulty/SYSTEM.md"
_MAX_EXCERPT_CHARS = 1800
_SOURCE_LIMITS = {"syllabus": 1, "textbook": 1}
_SOURCE_TYPES = frozenset(_SOURCE_LIMITS)
_TOKEN_PATTERN = re.compile(r"[a-z][a-z0-9'-]{2,}|\d+(?:\.\d+)*")
_STOP_WORDS = frozenset(
    {
        "about",
        "able",
        "also",
        "and",
        "apply",
        "can",
        "describe",
        "explain",
        "for",
        "from",
        "including",
        "know",
        "learning",
        "objective",
        "should",
        "student",
        "students",
        "that",
        "the",
        "their",
        "these",
        "this",
        "understand",
        "use",
        "using",
        "with",
    }
)


def difficulty_system_prompt() -> str:
    return (
        load_prompt_template(_PROMPT_PATH)
        .replace("__EASY_UPPER_BOUND__", f"{EASY_DIFFICULTY_UPPER_BOUND:g}")
        .replace("__MEDIUM_UPPER_BOUND__", f"{MEDIUM_DIFFICULTY_UPPER_BOUND:g}")
    )


class DifficultyCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    block_id: str = Field(min_length=1, max_length=80)
    evidence_role: Literal["syllabus", "textbook"]
    quote: str = Field(min_length=12, max_length=600)


class ModelDifficultyAssessment(BaseModel):
    """Direct, evidence-grounded D-level estimate; never an official rating."""

    model_config = ConfigDict(extra="forbid", strict=True)

    code: str = Field(min_length=1, max_length=80)
    evidence_sufficient: bool
    difficulty_score: float = Field(ge=0, le=1)
    relative_position: float = Field(ge=0, le=1)
    cognitive_demand: float = Field(ge=0, le=1)
    abstraction: float = Field(ge=0, le=1)
    prerequisite_breadth: int = Field(ge=0, le=12)
    procedural_depth: int = Field(ge=1, le=20)
    representation_switching: float = Field(ge=0, le=1)
    expected_steps: int = Field(ge=1, le=20)
    common_misconceptions: list[str] = Field(default_factory=list, max_length=6)
    confidence: float = Field(ge=0.05, le=0.45)
    rationale: str = Field(min_length=1, max_length=800)
    citations: list[DifficultyCitation] = Field(min_length=2, max_length=6)


class ModelDifficultyBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    assessments: list[ModelDifficultyAssessment] = Field(min_length=1, max_length=50)


class DifficultyAssessmentProvider(Protocol):
    model: str
    batch_size: int

    def assess_batch(
        self,
        subject_pack: SubjectPack,
        *,
        unit_outline: Sequence[Mapping[str, Any]],
        targets: Sequence[Mapping[str, Any]],
    ) -> dict[str, ModelDifficultyAssessment]: ...


def build_difficulty_targets(candidate: CurriculumCandidate) -> list[dict[str, Any]]:
    units = {unit.code: unit for unit in candidate.units}
    objectives_by_topic: dict[str, list[Any]] = {}
    for objective in candidate.objectives:
        objectives_by_topic.setdefault(objective.parent, []).append(objective)

    targets: list[dict[str, Any]] = []
    for topic in candidate.topics:
        children = objectives_by_topic.get(topic.code, [])
        targets.append(
            {
                "code": topic.code,
                "parent": topic.unit_code,
                "unit_code": topic.unit_code,
                "unit_title": units[topic.unit_code].title,
                "node_type": "topic",
                "title": topic.title,
                "description": "; ".join(item.title for item in children),
                "child_codes": [item.code for item in children],
            }
        )
        for objective in children:
            targets.append(
                {
                    "code": objective.code,
                    "parent": objective.parent,
                    "unit_code": topic.unit_code,
                    "unit_title": units[topic.unit_code].title,
                    "node_type": "learning_objective",
                    "title": objective.title,
                    "description": objective.description,
                    "child_codes": [],
                }
            )
    return targets


def build_evidence_materials(
    targets: Sequence[Mapping[str, Any]],
    blocks: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    eligible = [_eligible_block(block) for block in blocks]
    eligible = [block for block in eligible if block is not None]
    by_source = {
        source_type: [block for block in eligible if block["source_type"] == source_type]
        for source_type in _SOURCE_TYPES
    }
    missing_sources = [source_type for source_type, rows in by_source.items() if not rows]
    if missing_sources:
        raise ValueError(
            "Core knowledge base lacks difficulty evidence sources: "
            + ", ".join(sorted(missing_sources))
        )

    document_frequency = Counter[str]()
    for block in eligible:
        document_frequency.update(set(block["tokens"]))
    document_count = len(eligible)

    materials: dict[str, dict[str, Any]] = {}
    uncovered: list[str] = []
    for target in targets:
        query_tokens = _tokens(
            " ".join(
                str(target.get(field) or "") for field in ("title", "description", "unit_title")
            )
        )
        evidence: list[dict[str, Any]] = []
        for source_type, source_blocks in by_source.items():
            ranked = sorted(
                (
                    (
                        _match_score(
                            target, query_tokens, block, document_frequency, document_count
                        ),
                        block,
                    )
                    for block in source_blocks
                ),
                key=lambda item: (-item[0], item[1]["id"]),
            )
            selected = [item for item in ranked[: _SOURCE_LIMITS[source_type]] if item[0] > 0]
            if not selected:
                uncovered.append(f"{target['code']}:{source_type}")
                continue
            for score, block in selected:
                excerpt, excerpt_start = _focused_excerpt(block["content"], query_tokens)
                evidence.append(
                    {
                        "block_id": block["id"],
                        "document_id": block["document_id"],
                        "evidence_role": source_type,
                        "page": block["page"],
                        "section": block["section"],
                        "section_path": block["section_path"],
                        "content_hash": block["content_hash"],
                        "match_score": round(score, 6),
                        "excerpt_start": excerpt_start,
                        "excerpt": excerpt,
                    }
                )
        materials[str(target["code"])] = {**dict(target), "evidence": evidence}
    if uncovered:
        raise ValueError(
            "No relevant core evidence block for difficulty targets: " + ", ".join(uncovered[:20])
        )
    return materials


def difficulty_input_hash(
    *,
    candidate_hash: str,
    knowledge_base_version_id: str,
    materials: Mapping[str, Mapping[str, Any]],
) -> str:
    prompt_hash = hashlib.sha256(difficulty_system_prompt().encode("utf-8")).hexdigest()
    payload = {
        "method": DIFFICULTY_METHOD,
        "matcher": EVIDENCE_MATCHER_VERSION,
        "prompt_hash": prompt_hash,
        "candidate_hash": candidate_hash,
        "knowledge_base_version_id": knowledge_base_version_id,
        "targets": [
            {
                "code": code,
                "title": material["title"],
                "description": material["description"],
                "evidence": [
                    {
                        "block_id": evidence["block_id"],
                        "content_hash": evidence["content_hash"],
                        "excerpt_start": evidence["excerpt_start"],
                    }
                    for evidence in material["evidence"]
                ],
            }
            for code, material in sorted(materials.items())
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_assessment_evidence(
    assessment: ModelDifficultyAssessment,
    material: Mapping[str, Any],
) -> None:
    if not assessment.evidence_sufficient:
        raise ValueError(f"Model reported insufficient evidence for {assessment.code}")
    evidence_by_id = {str(item["block_id"]): item for item in material["evidence"]}
    cited_roles: set[str] = set()
    for citation in assessment.citations:
        evidence = evidence_by_id.get(citation.block_id)
        if evidence is None:
            raise ValueError(
                f"Difficulty citation for {assessment.code} references unprovided block "
                f"{citation.block_id}"
            )
        if citation.evidence_role != evidence["evidence_role"]:
            raise ValueError(f"Difficulty citation role mismatch for {assessment.code}")
        if _normalize_quote(citation.quote) not in _normalize_quote(str(evidence["excerpt"])):
            raise ValueError(
                f"Difficulty citation for {assessment.code} is not a verbatim input quote"
            )
        cited_roles.add(citation.evidence_role)
    if cited_roles != _SOURCE_TYPES:
        raise ValueError(
            f"Difficulty assessment {assessment.code} must cite syllabus and textbook evidence"
        )


class LiteLLMDifficultyAssessmentProvider:
    """Directly rate bounded target batches against supplied core evidence."""

    def __init__(
        self,
        settings: Settings,
        *,
        structured_model: StructuredModelPort | None = None,
    ) -> None:
        credential = settings.llm_api_key
        if structured_model is None and (credential is None or not credential.get_secret_value()):
            raise RuntimeError(
                "LLM credential is required for evidence-grounded difficulty ratings"
            )
        self.model = settings.knowledge_difficulty_model
        self.api_base = settings.llm_base_url
        self.api_key = "" if credential is None else credential.get_secret_value()
        self.reasoning_effort = settings.knowledge_difficulty_reasoning_effort
        self.timeout = settings.knowledge_difficulty_timeout
        self.batch_size = settings.knowledge_difficulty_batch_size
        self.runner = StructuredTaskRunner(
            structured_model
            or LiteLLMStructuredModel(
                model=self.model,
                provider=settings.litellm_provider,
                api_base=self.api_base,
                api_key=self.api_key,
                reasoning_effort=self.reasoning_effort,
                max_retries=1,
            )
        )

    def assess_batch(
        self,
        subject_pack: SubjectPack,
        *,
        unit_outline: Sequence[Mapping[str, Any]],
        targets: Sequence[Mapping[str, Any]],
    ) -> dict[str, ModelDifficultyAssessment]:
        if not targets or len(targets) > self.batch_size:
            raise ValueError(f"Difficulty batch must contain 1..{self.batch_size} targets")
        unit_codes = {str(item["unit_code"]) for item in targets}
        if len(unit_codes) != 1:
            raise ValueError("Difficulty targets from different units cannot share a batch")
        expected = {str(item["code"]) for item in targets}
        task = StructuredTask(
            system_prompt=difficulty_system_prompt(),
            user_content=json.dumps(
                {
                    "subject": subject_pack.title,
                    "unit": {
                        "code": next(iter(unit_codes)),
                        "targets": [_target_summary(item) for item in unit_outline],
                    },
                    "targets_to_rate": [dict(item) for item in targets],
                },
                ensure_ascii=False,
            ),
        )
        payload = self.runner.run(task, ModelDifficultyBatch, timeout=self.timeout)
        actual = {item.code for item in payload.assessments}
        if actual != expected or len(payload.assessments) != len(expected):
            raise ValueError(
                "Difficulty batch code mismatch; "
                f"missing={sorted(expected - actual)}, unexpected={sorted(actual - expected)}"
            )
        materials = {str(item["code"]): item for item in targets}
        for assessment in payload.assessments:
            validate_assessment_evidence(assessment, materials[assessment.code])
        return {item.code: item for item in payload.assessments}


def _eligible_block(block: Mapping[str, Any]) -> dict[str, Any] | None:
    metadata = block.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    source_type = str(metadata.get("source_type") or "")
    if source_type not in _SOURCE_TYPES:
        return None
    if source_type == "textbook" and metadata.get("authority_tier") != "licensed_core":
        return None
    content = str(block.get("content") or "").strip()
    if not content:
        return None
    return {
        "id": str(block["id"]),
        "document_id": str(block["document_id"]),
        "source_type": source_type,
        "page": block.get("page"),
        "section": block.get("section"),
        "section_path": list(block.get("section_path") or []),
        "content": content,
        "content_hash": str(block.get("content_hash") or ""),
        "knowledge_codes": {str(code) for code in block.get("knowledge_codes") or []},
        "tokens": _tokens(
            " ".join(
                [
                    str(block.get("section") or ""),
                    " ".join(str(item) for item in block.get("section_path") or []),
                    content,
                ]
            )
        ),
    }


def _tokens(value: str) -> set[str]:
    return {token for token in _TOKEN_PATTERN.findall(value.casefold()) if token not in _STOP_WORDS}


def _match_score(
    target: Mapping[str, Any],
    query_tokens: set[str],
    block: Mapping[str, Any],
    document_frequency: Counter[str],
    document_count: int,
) -> float:
    if not query_tokens:
        return 0
    weights = {
        token: math.log((document_count + 1) / (document_frequency[token] + 1)) + 1
        for token in query_tokens
    }
    score = sum(weights[token] for token in query_tokens & block["tokens"]) / sum(weights.values())
    knowledge_codes = block["knowledge_codes"]
    if str(target["code"]) in knowledge_codes:
        score += 4
    if str(target["parent"]) in knowledge_codes:
        score += 2
    if knowledge_codes.intersection(str(code) for code in target.get("child_codes") or []):
        score += 1
    title = str(target.get("title") or "").casefold().strip()
    section_text = " ".join(
        [str(block.get("section") or ""), *[str(item) for item in block["section_path"]]]
    ).casefold()
    if title and title in section_text:
        score += 1
    return score


def _focused_excerpt(content: str, query_tokens: set[str]) -> tuple[str, int]:
    if len(content) <= _MAX_EXCERPT_CHARS:
        return content, 0
    lowered = content.casefold()
    positions = [lowered.find(token) for token in query_tokens]
    positions = [position for position in positions if position >= 0]
    center = min(positions) if positions else 0
    start = max(0, min(len(content) - _MAX_EXCERPT_CHARS, center - _MAX_EXCERPT_CHARS // 3))
    end = start + _MAX_EXCERPT_CHARS
    return content[start:end], start


def _normalize_quote(value: str) -> str:
    return " ".join(value.split())


def _target_summary(target: Mapping[str, Any]) -> dict[str, str]:
    return {
        "code": str(target["code"]),
        "node_type": str(target["node_type"]),
        "parent": str(target["parent"]),
        "title": str(target["title"]),
        "description": str(target.get("description") or ""),
    }
