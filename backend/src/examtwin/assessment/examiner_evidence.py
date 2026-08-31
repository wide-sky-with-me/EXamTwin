from __future__ import annotations

import json
import re
from statistics import mean
from typing import Any

from examtwin.knowledge.public import CorpusRepository, DifficultyRepository, difficulty_label
from examtwin.platform.cache_paths import MarkdownCacheMissing, resolve_markdown_cache_path
from examtwin.platform.config import Settings, get_settings
from examtwin.platform.database.session import utcnow

QUESTION_RE = re.compile(r"(?im)^##\s+QUESTION\s+0*(\d+)\s*$")
PERCENT_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*%")
EVIDENCE_TERMS = (
    "%",
    "one third",
    "two thirds",
    "three quarters",
    "half of",
    "majority",
    "well answered",
    "not so well answered",
    "less well answered",
    "proved difficult",
    "most challenging",
    "more challenging",
    "found this difficult",
)
NEGATIVE_TERMS = (
    "no marks",
    "did not",
    "unable",
    "failed",
    "incorrect",
    "not attempt",
    "made no further progress",
)
POSITIVE_TERMS = (
    "correct",
    "full mark",
    "full three",
    "full four",
    "all marks",
    "both marks",
    "awarded the mark",
    "perfect solution",
)

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "P1.1": ("factor theorem", "quadratic", "surds", "polynomial", "inequalit"),
    "P1.2": ("coordinate", "straight line", "gradient"),
    "P1.3": ("differentiat", "derivative", "tangent", "stationary"),
    "P1.4": ("integrat", "area under"),
    "P1.5": ("sequence", "series"),
    "PP1.1": ("circle",),
    "PP1.2": ("trigon", "sine", "cosine", "radian"),
    "PP1.3": ("logarith", "exponential"),
    "S1.1": ("probability",),
    "S1.2": ("random variable", "expectation"),
    "S1.3": ("binomial", "bernoulli"),
    "M1.1": ("constant acceleration", "suvat"),
    "M1.2": ("variable acceleration",),
    "M1.3": ("force", "newton"),
    "M1.4": ("momentum", "impulse"),
    "P2.1": ("function", "partial fraction", "modulus", "algebra"),
    "P2.2": ("sequence", "series", "binomial expansion"),
    "P2.3": ("coordinate", "parametric curve"),
    "P2.4": ("trigon", "sine", "cosine", "secant"),
    "P2.5": ("logarith", "exponential"),
    "P2.6": ("differentiat", "derivative", "chain rule", "quotient rule"),
    "P2.7": ("integrat", "integration by parts", "substitution"),
    "P2.8": ("differential equation",),
    "P2.9": ("iteration", "trapezium", "numerical"),
    "P2.10": ("vector",),
    "S2.1": ("poisson",),
    "S2.2": ("continuous random", "probability density"),
    "S2.3": ("exponential distribution",),
    "S2.4": ("normal distribution",),
    "S2.5": ("confidence interval", "estimat"),
    "S2.6": ("hypothesis", "significance"),
    "M2.1": ("modelling",),
    "M2.2": ("kinematic", "velocity", "acceleration"),
    "M2.3": ("static", "equilibrium", "centre of mass", "moment"),
    "M2.4": ("newton", "resistance", "force"),
    "M2.5": ("projectile",),
    "M2.6": ("work", "energy", "power"),
    "M2.7": ("circular motion", "angular speed"),
}

UNIT_CODES = {
    "P1": {"P1.1", "P1.2", "P1.3", "P1.4", "P1.5"},
    "PSM1": {
        "PP1.1",
        "PP1.2",
        "PP1.3",
        "S1.1",
        "S1.2",
        "S1.3",
        "M1.1",
        "M1.2",
        "M1.3",
        "M1.4",
    },
    "P2": {f"P2.{number}" for number in range(1, 11)},
    "S2": {f"S2.{number}" for number in range(1, 7)},
    "M2": {f"M2.{number}" for number in range(1, 8)},
}


def _question_sections(text: str) -> list[tuple[str, str]]:
    matches = list(QUESTION_RE.finditer(text))
    return [
        (
            match.group(1),
            text[match.end() : matches[index + 1].start() if index + 1 < len(matches) else None],
        )
        for index, match in enumerate(matches)
    ]


def _sentences(text: str) -> list[str]:
    flattened = re.sub(r"\s+", " ", text)
    return [
        item.strip() for item in re.split(r"(?<=[.!?])\s+(?=[A-Z(])", flattened) if item.strip()
    ]


def _qualitative_score(sentence: str) -> float | None:
    lower = sentence.lower()
    if "most challenging" in lower or "majority of students scored no marks" in lower:
        return 0.85
    if "proved difficult" in lower or "found this difficult" in lower:
        return 0.76
    if "more challenging" in lower:
        return 0.70
    if "not so well answered" in lower or "less well answered" in lower:
        return 0.66
    if "very well answered" in lower:
        return 0.18
    if "well answered" in lower:
        return 0.30
    return None


def _numeric_score(sentence: str) -> list[float]:
    lower = sentence.lower()
    if "at least one" in lower or "at least 2" in lower or "at least two" in lower:
        return []
    values = [float(match.group("value")) / 100 for match in PERCENT_RE.finditer(sentence)]
    if not values:
        return []
    if any(term in lower for term in NEGATIVE_TERMS):
        return values
    if any(term in lower for term in POSITIVE_TERMS):
        return [1 - value for value in values]
    return []


def _knowledge_codes(text: str, unit_code: str | None) -> list[str]:
    lower = text.lower()
    allowed = UNIT_CODES.get(unit_code or "", set(TOPIC_KEYWORDS))
    scores = {
        code: sum(keyword in lower for keyword in keywords)
        for code, keywords in TOPIC_KEYWORDS.items()
        if code in allowed
    }
    return [
        code
        for code, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        if score > 0
    ][:3]


def extract_examiner_evidence(
    documents: CorpusRepository,
    difficulties: DifficultyRepository,
    settings: Settings | None = None,
) -> dict[str, int]:
    settings = settings or get_settings()
    rows = documents.list(
        source_types=["examiner_report"],
    )
    rows = [row for row in rows if row.get("markdown_path")]
    document_count = 0
    questions = 0
    numeric_questions = 0
    observations: list[dict[str, Any]] = []
    for row in rows:
        try:
            markdown_path = resolve_markdown_cache_path(
                settings,
                str(row["id"]),
                str(row["markdown_path"]),
            )
        except MarkdownCacheMissing:
            continue
        text = markdown_path.read_text(encoding="utf-8", errors="ignore")
        extracted = 0
        for number, section in _question_sections(text):
            evidence = [
                sentence
                for sentence in _sentences(section)
                if any(term in sentence.lower() for term in EVIDENCE_TERMS)
            ]
            numeric_scores = [score for sentence in evidence for score in _numeric_score(sentence)]
            qualitative_scores = [
                score
                for sentence in evidence
                if (score := _qualitative_score(sentence)) is not None
            ]
            if numeric_scores:
                score = mean(numeric_scores)
                level = "A"
                confidence = 0.82
                numeric_questions += 1
            elif qualitative_scores:
                score = mean(qualitative_scores)
                level = "B"
                confidence = 0.65
            else:
                continue
            score = max(0.0, min(1.0, score))
            label = difficulty_label(score)
            question_ref = (
                f"{row['pair_key']}:Q{int(number)}"
                if row["pair_key"]
                else f"{row['filename']}:Q{int(number)}"
            )
            source_ref = f"{row['path']}#QUESTION-{int(number):02d}"
            observations.append(
                {
                    "source_document_id": row["id"],
                    "question_ref": question_ref,
                    "pair_key": row["pair_key"],
                    "question_number": str(int(number)),
                    "difficulty_score": round(score, 4),
                    "difficulty_label": label,
                    "confidence": confidence,
                    "evidence_level": level,
                    "knowledge_codes_json": json.dumps(_knowledge_codes(section, row["unit_code"])),
                    "evidence_json": json.dumps(evidence, ensure_ascii=False),
                    "source_ref": source_ref,
                    "updated_at": utcnow(),
                }
            )
            questions += 1
            extracted += 1
        if extracted:
            document_count += 1
    difficulties.upsert_questions(observations)
    return {
        "documents_with_evidence": document_count,
        "question_rows": questions,
        "numeric_question_rows": numeric_questions,
    }


def list_question_difficulty(
    repository: DifficultyRepository,
    *,
    pair_key: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    return repository.list_questions(
        pair_key=pair_key,
        limit=limit,
    )
