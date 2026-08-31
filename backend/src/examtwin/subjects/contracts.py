from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SubjectSkill:
    """Subject policy and the capabilities an answering Agent may use."""

    name: str
    subject_codes: tuple[str, ...]
    instructions: str
    tool_names: tuple[str, ...]
    required_tool_names: tuple[str, ...] = ()
    mandatory_tool_names: tuple[str, ...] = ()
    visual_tool_selector: Callable[[str], str | None] | None = None
    source_plot_overlay_selector: Callable[[str], str | None] | None = None
    version: str = "1"
    digest: str = ""
    package_digest: str = ""

    def required_visual_tool(self, question: str) -> str | None:
        if self.visual_tool_selector is None:
            return None
        tool_name = self.visual_tool_selector(question)
        if tool_name is not None and tool_name not in self.tool_names:
            raise ValueError(
                f"Visual tool selector returned an unregistered capability: {tool_name}"
            )
        return tool_name

    def source_plot_overlay_mode(self, question: str) -> str | None:
        if self.source_plot_overlay_selector is None:
            return None
        return self.source_plot_overlay_selector(question)


class CurriculumTextNormalizer(Protocol):
    """Reviewed subject policy for wording repairs after structural extraction."""

    key: str

    def objective_title(self, topic_title: str, raw_title: str) -> str: ...


class DefaultCurriculumTextNormalizer:
    key = "default-v1"

    def objective_title(self, topic_title: str, raw_title: str) -> str:
        del topic_title
        title = raw_title.strip().strip(";")
        if title.lower().startswith("and "):
            title = title[4:].strip()
        title = title[:1].upper() + title[1:]
        return title.rstrip(".") + "."


DEFAULT_CURRICULUM_NORMALIZER = DefaultCurriculumTextNormalizer()


@dataclass(frozen=True)
class BoardPack:
    id: str
    name: str
    official_source_types: frozenset[str]
    filename_subject_code_pattern: str | None = None

    def subject_code_from_filename(self, filename: str) -> str | None:
        if self.filename_subject_code_pattern is None:
            return None
        match = re.search(self.filename_subject_code_pattern, filename.lower())
        if match is None:
            return None
        return match.group("subject_code")


@dataclass(frozen=True)
class UnitRule:
    """Small subject rule that maps extracted topic codes to an assessment unit."""

    code: str
    title: str
    strand: str
    source_page: int
    topic_prefixes: tuple[str, ...]

    def matches(self, topic_code: str) -> bool:
        return any(
            topic_code == prefix or topic_code.startswith(f"{prefix}.")
            for prefix in self.topic_prefixes
        )


@dataclass(frozen=True)
class SubjectPack:
    """Reviewed parsing and publication policy; never a copy of curriculum content."""

    id: str
    subject_code: str
    title: str
    board: BoardPack
    specification_ref: str
    unit_rules: tuple[UnitRule, ...]
    topic_code_pattern: str
    unit_patterns: tuple[tuple[str, str], ...]
    paper_unit_map: dict[str, str]
    minimum_topics: int
    minimum_objectives: int
    extractor_key: str = "structured-markdown-v1"
    curriculum_normalizer: CurriculumTextNormalizer = DEFAULT_CURRICULUM_NORMALIZER

    def point_id(self, code: str) -> str:
        return f"{self.subject_code}:{code}"

    def pair_key(self, year: int, session: str, unit: str) -> str:
        return f"{self.subject_code}:{year}:{session}:{unit}"

    def parse_unit(self, text: str) -> str | None:
        normalized = re.sub(r"[-_]+", " ", text.lower())
        for pattern, unit in self.unit_patterns:
            if re.search(pattern, normalized):
                return unit
        paper = re.search(r"\bpaper\s*([0-9]+)\b", normalized)
        return self.paper_unit_map.get(paper.group(1)) if paper else None

    def resolve_topic_unit(self, topic_code: str) -> UnitRule | None:
        matches = [rule for rule in self.unit_rules if rule.matches(topic_code)]
        if not matches:
            return None
        return max(
            matches,
            key=lambda rule: max(len(prefix) for prefix in rule.topic_prefixes),
        )

    def topic_heading_pattern(self) -> re.Pattern[str]:
        return re.compile(
            rf"^(?:#{{1,6}}\s*)?(?P<code>{self.topic_code_pattern})"
            rf"(?:\s*:\s*|\s+)(?P<title>.+?)\s*$"
        )
