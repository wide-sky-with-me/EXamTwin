"""normalize persisted rubric subparts and mark labels

Revision ID: 20260810_0019
Revises: 20260809_0018
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0019"
down_revision: str | None = "20260809_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RUBRIC_CRITERIA = sa.table(
    "rubric_criteria",
    sa.column("id", sa.Text()),
    sa.column("question_number", sa.Text()),
    sa.column("subpart", sa.Text()),
    sa.column("mark_type", sa.Text()),
    sa.column("max_marks", sa.Float()),
)
_RUBRIC_SETS = sa.table(
    "rubric_sets",
    sa.column("id", sa.Text()),
    sa.column("warnings_json", sa.Text()),
)
_QUESTION_PREFIX = re.compile(
    r"^\s*(?:question|q)?\s*0*(?P<number>\d+)(?=\s*(?:\(|[._/-]))",
    re.IGNORECASE,
)
_QUESTION_NUMBER = re.compile(r"^\s*(?:question|q)?\s*0*(?P<number>\d+)", re.IGNORECASE)
_MARK_TYPE = re.compile(r"^(?P<kind>[MmABE])(?P<marks>\d+)?(?P<follow_through>(?i:ft))?$")


def _normalized_subpart(question_number: str, subpart: str) -> str:
    value = subpart.strip()
    prefix = _QUESTION_PREFIX.match(value)
    target = _QUESTION_NUMBER.match(question_number)
    if prefix is None or target is None:
        return value
    if int(prefix.group("number")) != int(target.group("number")):
        return value
    value = value[prefix.end() :].strip()
    return re.sub(r"^[._/-]\s*", "", value) or "whole"


def _normalized_mark_type(mark_type: str | None, max_marks: float) -> str | None:
    if mark_type is None:
        return None
    value = mark_type.strip()
    match = _MARK_TYPE.fullmatch(value)
    if match is None or match.group("marks") is not None or not max_marks.is_integer():
        return value
    follow_through = "ft" if match.group("follow_through") else ""
    return f"{match.group('kind')}{int(max_marks)}{follow_through}"


def _warning_key(warning: str) -> str:
    normalized = re.sub(r"\W+", " ", warning.replace("_", " ").casefold()).strip()
    missing_page_phrases = (
        "does not provide",
        "does not include",
        "does not specify",
        "not specified",
        "not identify",
        "is null",
    )
    if "page" in normalized and any(phrase in normalized for phrase in missing_page_phrases):
        return "source-page-unavailable"
    return normalized


def _normalized_warnings(raw_warnings: str) -> str:
    warnings = json.loads(raw_warnings)
    if not isinstance(warnings, list) or not all(isinstance(warning, str) for warning in warnings):
        raise RuntimeError("rubric_sets.warnings_json must contain a list of strings")
    keys: list[str] = []
    best_by_key: dict[str, str] = {}
    for warning in warnings:
        key = _warning_key(warning)
        if key not in best_by_key:
            keys.append(key)
            best_by_key[key] = warning
        elif len(warning) > len(best_by_key[key]):
            best_by_key[key] = warning
    return json.dumps([best_by_key[key] for key in keys], ensure_ascii=False)


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.select(_RUBRIC_CRITERIA)).mappings().all()
    for row in rows:
        subpart = _normalized_subpart(str(row["question_number"]), str(row["subpart"]))
        mark_type = _normalized_mark_type(row["mark_type"], float(row["max_marks"]))
        if subpart == row["subpart"] and mark_type == row["mark_type"]:
            continue
        connection.execute(
            sa.update(_RUBRIC_CRITERIA)
            .where(_RUBRIC_CRITERIA.c.id == row["id"])
            .values(subpart=subpart, mark_type=mark_type)
        )

    rubric_sets = connection.execute(sa.select(_RUBRIC_SETS)).mappings().all()
    for row in rubric_sets:
        warnings_json = _normalized_warnings(str(row["warnings_json"]))
        if warnings_json == row["warnings_json"]:
            continue
        connection.execute(
            sa.update(_RUBRIC_SETS)
            .where(_RUBRIC_SETS.c.id == row["id"])
            .values(warnings_json=warnings_json)
        )


def downgrade() -> None:
    pass
