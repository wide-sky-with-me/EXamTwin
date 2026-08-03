from __future__ import annotations

import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from examtwin.answering_agent.contracts import AgentEventSink, QuestionImage
from examtwin.config import Settings
from examtwin.persistence.knowledge_repository import KnowledgeRepository
from examtwin.schemas.evidence import Citation
from examtwin.schemas.knowledge import AskRequest
from examtwin.schemas.papers import (
    PaperAnswerResponse,
    PaperKnowledgeReference,
    PaperQuestionAnswer,
)
from examtwin.services.inventory import parse_exam_identity
from examtwin.services.knowledge import list_knowledge_points
from examtwin.services.model_json import parse_json_response
from examtwin.services.paper_parsing import (
    _tokens,
    question_spec_from_item,
    reconcile_question_source_pages,
    upload_to_markdown,
)
from examtwin.services.providers import build_llm
from examtwin.services.rag import RagService
from examtwin.services.subject_context import SubjectContext

PAGE_SECTION = re.compile(
    r"(?=<!--\s*(?:pages?\s+\d+|examtwin:physical-page=\d+))",
    re.IGNORECASE,
)


def _split_markdown_batches(markdown: str, *, max_chars: int) -> list[str]:
    if len(markdown) <= max_chars:
        return [markdown]
    sections = [item for item in PAGE_SECTION.split(markdown) if item.strip()]
    if len(sections) == 1:
        overlap = min(4_000, max_chars // 10)
        return [
            markdown[max(0, start - overlap) : start + max_chars]
            for start in range(0, len(markdown), max_chars - overlap)
        ]

    batches: list[str] = []
    current: list[str] = []
    current_size = 0
    for section in sections:
        if current and current_size + len(section) > max_chars:
            batches.append("".join(current))
            current = [current[-1], section]
            current_size = sum(len(item) for item in current)
        else:
            current.append(section)
            current_size += len(section)
    if current:
        batches.append("".join(current))
    return batches


def _merge_split_questions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for item in items:
        number = str(item.get("number", "?")).strip()
        key = re.sub(r"\s+", "", number).lower()
        if not key or key == "?" or key not in positions:
            if key and key != "?":
                positions[key] = len(merged)
            merged.append(item)
            continue
        position = positions[key]
        previous = merged[position]
        previous_text = str(previous.get("question_markdown", ""))
        candidate_text = str(item.get("question_markdown", ""))
        if len(candidate_text) > len(previous_text):
            merged[position] = item
    return merged


class PaperAnswerService:
    def __init__(
        self,
        settings: Settings,
        subject: SubjectContext,
        *,
        knowledge_repository: KnowledgeRepository | None = None,
        rag: Any | None = None,
        splitter: Callable[[str, list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
        parser: Callable[[Settings, str, bytes], str] | None = None,
        catalog_loader: Callable[[str | None], list[dict[str, Any]]] | None = None,
    ):
        self.settings = settings
        self.subject = subject
        self.knowledge_repository = knowledge_repository
        self.rag = rag or RagService(settings, subject, knowledge_repository)
        self.splitter = splitter or self._split_with_llm
        self.parser = parser or upload_to_markdown
        self.catalog_loader = catalog_loader or self._load_catalog

    def _load_catalog(self, unit_code: str | None) -> list[dict[str, Any]]:
        if self.knowledge_repository is None:
            raise RuntimeError("Knowledge repository is required to load the question catalog")
        points = list_knowledge_points(
            self.knowledge_repository,
            subject_code=self.subject.subject_code,
            unit_code=unit_code,
        )
        detailed = [
            point for point in points if point["features"].get("node_type") == "learning_objective"
        ]
        return detailed or [
            point for point in points if point["features"].get("node_type") == "topic"
        ]

    def _catalog(self, unit_code: str | None) -> list[dict[str, Any]]:
        return self.catalog_loader(unit_code)

    def _split_with_llm(
        self,
        markdown: str,
        catalog: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        catalog_text = "\n".join(f"- {point['code']}: {point['title']}" for point in catalog)
        def split_batch(batch: str) -> list[dict[str, Any]]:
            prompt = f"""
You extract top-level questions from a {self.subject.pack.title} examination paper.
MinerU may omit a printed question number or place a question inside an HTML table.
Reconstruct the ordered top-level questions using surrounding numbers, mark labels,
page turns and subpart labels. Keep every subpart with its top-level question. Ignore
instructions, cover pages, examiner-use tables and blank answer lines. Do not solve.
Sections marked with physical page comments may already have been reconciled against
the page images. Treat that visually reviewed Markdown as the primary source.
The input may include a PDF text-layer recovery appendix after the MinerU Markdown.
It can duplicate content, but it may contain wording that MinerU omitted. Merge the two
sources without duplication and restore missing subparts from the recovery text.
Before returning, verify that every visible top-level number, subpart label and mark
value in the primary source appears exactly once in the resulting question list.
Each visually reviewed PDF page starts with an immutable
`<!-- examtwin:physical-page=N -->` marker. The application derives source pages from
question positions after your response, so `source_pages` is only a compatibility
field and will never be trusted as provenance.

For each question, assign up to four best matching knowledge codes from the supplied
catalog. Never invent a code.
Set `requires_visual_context` to true only when solving the question depends on a
printed figure, diagram, graph, chart, plot, shaded region, or other spatial visual
information. It must be false for text-only probability/algebra questions even though
their source PDF pages are available.
Extract an `answer_requirements` item for every visible subpart, or one item labelled
`whole` when there are no subparts. Preserve the printed subpart label and marks.
`answer_kind` must be one of text, numeric, expression, proof, table, math_plot,
math_diagram, image. Copy an explicit accuracy instruction and required units.
Set `required_tool` only when the candidate must create that answer artifact:
math_plot for coordinate/statistical plots, math_diagram for exact geometry or other
vector diagrams, image_generate only for a genuinely pictorial response. Merely
reading a printed source figure does not require an answer artifact.

Return only:
{{
  "questions": [
    {{
      "number": "1",
      "question_markdown": "complete question with all subparts",
      "source_pages": [2, 3],
      "requires_visual_context": false,
      "total_marks": 4,
      "answer_requirements": [
        {{
          "label": "(a)",
          "marks": 2,
          "answer_kind": "numeric",
          "accuracy": "three significant figures",
          "units": [],
          "required_tool": null
        }}
      ],
      "knowledge_codes": ["P2.7.O03"]
    }}
  ]
}}

Knowledge catalog:
{catalog_text}

Paper Markdown:
{batch}
""".strip()
            payload = parse_json_response(
                build_llm(
                    self.settings,
                    model=self.settings.paper_split_model,
                    timeout=self.settings.paper_split_timeout,
                    max_retries=1,
                    reasoning_effort=self.settings.paper_split_reasoning_effort,
                )
                .complete(prompt)
                .text
            )
            questions = payload.get("questions")
            if not isinstance(questions, list):
                raise ValueError("模型没有返回可用的试卷题目列表")
            return [item for item in questions if isinstance(item, dict)]

        extracted: list[dict[str, Any]] = []
        for batch in _split_markdown_batches(
            markdown,
            max_chars=self.settings.paper_split_max_chars,
        ):
            extracted.extend(split_batch(batch))
        return _merge_split_questions(extracted)

    def _fallback_codes(
        self,
        question: str,
        catalog: list[dict[str, Any]],
    ) -> list[str]:
        question_tokens = _tokens(question)
        scores: list[tuple[float, str]] = []
        for point in catalog:
            features = point["features"]
            point_tokens = _tokens(f"{point['title']} {features.get('description', '')}")
            if not point_tokens:
                continue
            overlap = len(question_tokens & point_tokens) / len(point_tokens)
            if overlap:
                scores.append((overlap, point["code"]))
        return [code for _, code in sorted(scores, reverse=True)[:3]]

    def _knowledge_references(
        self,
        codes: list[str],
        catalog_by_code: dict[str, dict[str, Any]],
        answer_citations: list[Citation],
    ) -> list[PaperKnowledgeReference]:
        references: list[PaperKnowledgeReference] = []
        for code in codes:
            point = catalog_by_code.get(code)
            if not point:
                continue
            point_text = f"{point['title']} {point['features'].get('description', '')}"
            point_tokens = _tokens(point_text)
            related = [
                citation
                for citation in answer_citations
                if citation.knowledge_code == code
                or len(point_tokens & _tokens(citation.excerpt))
                >= (1 if len(point_tokens) <= 2 else 2)
            ]
            source_ref = str(point["source_ref"])
            stored = [
                Citation.model_validate(reference) for reference in point.get("references", [])
            ]
            merged: list[Citation] = []
            seen: set[tuple[Any, ...]] = set()
            for citation in [*stored, *related]:
                key = (
                    citation.document_id,
                    citation.source,
                    citation.page,
                    citation.section,
                    citation.excerpt[:240],
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(citation)
            references.append(
                PaperKnowledgeReference(
                    code=point["code"],
                    title=point["title"],
                    node_type=point["features"].get("node_type", "topic"),
                    difficulty_score=point["difficulty_score"],
                    difficulty_label=point["difficulty_label"],
                    difficulty_confidence=point["difficulty_confidence"],
                    evidence_level=point["evidence_level"],
                    source_ref=source_ref,
                    references=merged[:6],
                    definition=point.get("definition", ""),
                    breadcrumb=point.get("breadcrumb", ""),
                    path=point.get("path", []),
                    relations=point.get("relations", []),
                    difficulty=point.get("difficulty"),
                )
            )
        return references

    def _answer_one(
        self,
        item: dict[str, Any],
        catalog: list[dict[str, Any]],
        unit_code: str | None,
        pair_key: str | None = None,
        event_sink: AgentEventSink | None = None,
    ) -> PaperQuestionAnswer:
        number = str(item.get("number", "?")).strip() or "?"
        question = str(item.get("question_markdown", "")).strip()
        if not question:
            raise ValueError(f"第 {number} 题题干为空")
        raw_images = item.get("question_images", ())
        if not isinstance(raw_images, (list, tuple)) or not all(
            isinstance(image, QuestionImage) for image in raw_images
        ):
            raise ValueError(f"第 {number} 题原题页图不是可信的 QuestionImage")
        question_images = tuple(raw_images)
        question_spec = question_spec_from_item(item)
        raw_codes = item.get("knowledge_codes", [])
        codes = [str(code) for code in raw_codes] if isinstance(raw_codes, list) else []
        catalog_by_code = {point["code"]: point for point in catalog}
        codes = [code for code in codes if code in catalog_by_code]
        if not codes:
            codes = self._fallback_codes(question, catalog)
        knowledge_context = "\n".join(
            f"- {code}: {catalog_by_code[code]['title']} "
            f"{catalog_by_code[code]['features'].get('description', '')}"
            for code in codes
        )
        source_types = ["syllabus", "textbook", "question_paper"]
        if pair_key is not None:
            source_types.append("mark_scheme")
        response = self.rag.ask(
            AskRequest(
                question=(
                    f"Solve the following examination question completely. Show all necessary "
                    f"mathematical working. If the requested answer includes a sketch or "
                    f"construction, include a diagram.\n\n"
                    f"Relevant knowledge:\n{knowledge_context}\n\n{question}"
                ),
                subject_code=self.subject.subject_code,
                unit_code=unit_code,
                pair_key=pair_key,
                source_types=source_types,
                top_k=6,
            ),
            question_images=question_images,
            question_number=number,
            question_spec=question_spec,
            visual_request_text=question,
            event_sink=event_sink,
        )
        return PaperQuestionAnswer(
            number=number,
            question_markdown=question,
            answer_markdown=response.answer_markdown,
            diagrams=response.diagrams,
            images=response.images,
            citations=response.citations,
            knowledge_points=self._knowledge_references(
                codes,
                catalog_by_code,
                response.citations,
            ),
            confidence=response.confidence,
            grounded=response.grounded,
            warnings=[
                *response.warnings,
                *(
                    ["试卷身份未完整解析，本题未检索 Mark Scheme，以避免跨卷证据污染。"]
                    if pair_key is None
                    else []
                ),
            ],
        )

    def split_questions(
        self,
        markdown: str,
        *,
        unit_code: str | None = None,
    ) -> list[dict[str, Any]]:
        if len(markdown.strip()) < 20:
            raise ValueError("解析后的试卷内容过短，无法识别题目")
        catalog = self._catalog(unit_code)
        questions = self.splitter(markdown, catalog)
        normalized = [item for item in questions if str(item.get("question_markdown", "")).strip()]
        if not normalized:
            raise ValueError("没有识别到顶层题目，请检查试卷内容或 MinerU 解析结果")
        for item in normalized:
            spec = question_spec_from_item(item)
            item["answer_requirements"] = [part.model_dump(mode="json") for part in spec.subparts]
            item["total_marks"] = spec.total_marks
        return reconcile_question_source_pages(markdown, normalized)

    def answer_question(
        self,
        item: dict[str, Any],
        *,
        unit_code: str | None = None,
        pair_key: str | None = None,
        event_sink: AgentEventSink | None = None,
    ) -> PaperQuestionAnswer:
        return self._answer_one(
            item,
            self._catalog(unit_code),
            unit_code,
            pair_key,
            event_sink,
        )

    def answer(
        self,
        filename: str,
        content: bytes,
        *,
        unit_code: str | None = None,
    ) -> PaperAnswerResponse:
        markdown = self.parser(self.settings, filename, content).strip()
        normalized = self.split_questions(markdown, unit_code=unit_code)
        catalog = self._catalog(unit_code)
        pair_key = parse_exam_identity(
            Path(filename),
            "question_paper",
            self.subject.pack,
        )["pair_key"]

        answers: list[PaperQuestionAnswer | None] = [None] * len(normalized)
        worker_count = min(self.settings.paper_question_concurrency, len(normalized))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(self._answer_one, item, catalog, unit_code, pair_key): index
                for index, item in enumerate(normalized)
            }
            for future in as_completed(futures):
                index = futures[future]
                item = normalized[index]
                try:
                    answers[index] = future.result()
                except Exception as error:
                    answers[index] = PaperQuestionAnswer(
                        number=str(item.get("number", "?")),
                        question_markdown=str(item.get("question_markdown", "")),
                        answer_markdown="",
                        confidence=0,
                        grounded=False,
                        warnings=["该题作答失败，可单独重试。"],
                        error=str(error)[:500],
                    )

        completed = [answer for answer in answers if answer is not None]
        failed = sum(1 for answer in completed if answer.error is not None)
        return PaperAnswerResponse(
            filename=filename,
            detected_questions=len(completed),
            succeeded=len(completed) - failed,
            failed=failed,
            questions=completed,
        )
