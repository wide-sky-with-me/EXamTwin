from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from examtwin.assessment.answering_agent.contracts import (
    AgentEventSink,
    AgentRunLedger,
    QuestionImage,
)
from examtwin.assessment.answering_agent.finalization import citation_ids_in_markdown
from examtwin.assessment.paper_parsing import (
    QuestionSourcePageResolutionError,
    question_spec_from_item,
    reconcile_question_source_pages,
    upload_to_markdown,
)
from examtwin.assessment.rag import RagService
from examtwin.contracts.evidence import Citation
from examtwin.contracts.knowledge import AskRequest
from examtwin.contracts.papers import (
    PaperAnswerResponse,
    PaperKnowledgeReference,
    PaperQuestionAnswer,
)
from examtwin.knowledge.public import (
    KnowledgeRepository,
    list_knowledge_points,
    parse_exam_identity,
)
from examtwin.platform.agent_runtime.structured import (
    StructuredModelPort,
    StructuredTask,
    StructuredTaskRunner,
)
from examtwin.platform.config import Settings
from examtwin.platform.model_json import parse_json_response
from examtwin.platform.providers import build_llm
from examtwin.platform.structured_model import LiteLLMStructuredModel
from examtwin.subjects.public import SubjectContext

PAGE_SECTION = re.compile(
    r"(?=<!--\s*(?:pages?\s+\d+|examtwin:physical-page=\d+))",
    re.IGNORECASE,
)
SPLIT_CONTRACT_VERSION = "paper-question-split-v3"

SplitCheckpointLoader = Callable[[int, str], list[dict[str, Any]] | None]
SplitCheckpointSaver = Callable[[int, int, str, list[dict[str, Any]], float], None]


class _QuestionRepairGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    number: str = Field(min_length=1, max_length=32)
    candidate_indexes: list[int] = Field(min_length=1)


class _QuestionRepairPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    groups: list[_QuestionRepairGroup] = Field(min_length=1)


def _build_question_repair_model(settings: Settings) -> StructuredModelPort:
    api_key = settings.llm_provider_api_key
    if api_key is None:
        raise RuntimeError("Question structure repair requires OPENAI_COMPAT_API_KEY")
    return LiteLLMStructuredModel(
        model=settings.paper_split_model,
        api_base=settings.llm_provider_base_url,
        api_key=api_key.get_secret_value(),
        reasoning_effort=settings.paper_split_reasoning_effort,
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


def _question_number_identity(number: str) -> tuple[str, str | None, bool]:
    compact = re.sub(r"\s+", "", number).lower()
    exact = re.fullmatch(r"0*(\d+)", compact)
    if exact:
        canonical = str(int(exact.group(1)))
        return compact, canonical, True
    prefix = re.match(r"0*(\d+)", compact)
    canonical = str(int(prefix.group(1))) if prefix else None
    return compact, canonical, False


def _merge_split_questions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    identities = [_question_number_identity(str(item.get("number", "?")).strip()) for item in items]
    top_level_numbers = {
        canonical
        for _compact, canonical, is_top_level in identities
        if canonical is not None and is_top_level
    }
    merged: list[dict[str, Any]] = []
    merged_is_top_level: list[bool] = []
    positions: dict[str, int] = {}
    for item, (compact, canonical, is_top_level) in zip(items, identities, strict=True):
        key = canonical if canonical in top_level_numbers else compact
        if not key or key == "?" or key not in positions:
            if key and key != "?":
                positions[key] = len(merged)
            merged.append(item)
            merged_is_top_level.append(is_top_level)
            continue
        position = positions[key]
        previous = merged[position]
        previous_is_top_level = merged_is_top_level[position]
        if previous_is_top_level and not is_top_level:
            # Recovery text may split one complete top-level question into numbered fragments.
            continue
        if is_top_level and not previous_is_top_level:
            merged[position] = item
            merged_is_top_level[position] = True
            continue
        previous_text = str(previous.get("question_markdown", ""))
        candidate_text = str(item.get("question_markdown", ""))
        if len(candidate_text) > len(previous_text):
            replacement = dict(item)
            if is_top_level:
                replacement["number"] = previous.get("number", item.get("number"))
            merged[position] = replacement
    return merged


def _combine_repair_group(
    items: list[dict[str, Any]],
    group: _QuestionRepairGroup,
) -> dict[str, Any]:
    target_compact, target_canonical, _target_is_top_level = _question_number_identity(group.number)
    identities = [_question_number_identity(str(item.get("number", "?")).strip()) for item in items]
    if target_canonical is not None:
        identity_matches = any(canonical == target_canonical for _, canonical, _ in identities)
    else:
        identity_matches = any(compact == target_compact for compact, _, _ in identities)
    if not identity_matches:
        raise ValueError(f"结构修复模型为题组生成了无来源题号：{group.number}")

    exact_top_level = [
        item
        for item, (compact, canonical, is_top_level) in zip(items, identities, strict=True)
        if is_top_level
        and (
            canonical == target_canonical
            if target_canonical is not None
            else compact == target_compact
        )
    ]
    if exact_top_level:
        repaired = dict(
            max(
                exact_top_level,
                key=lambda item: len(str(item.get("question_markdown", ""))),
            )
        )
    else:
        repaired = dict(items[0])
        texts = list(
            dict.fromkeys(
                text for item in items if (text := str(item.get("question_markdown", "")).strip())
            )
        )
        repaired["question_markdown"] = "\n\n".join(texts)

    repaired["number"] = group.number.strip()
    repaired.pop("source_pages", None)
    repaired["requires_visual_context"] = any(
        bool(item.get("requires_visual_context")) for item in items
    )

    knowledge_codes: list[str] = []
    requirements: list[Any] = []
    requirement_keys: set[str] = set()
    for item in items:
        for code in item.get("knowledge_codes") or []:
            normalized_code = str(code).strip()
            if normalized_code and normalized_code not in knowledge_codes:
                knowledge_codes.append(normalized_code)
        for requirement in item.get("answer_requirements") or []:
            key = json.dumps(requirement, ensure_ascii=False, sort_keys=True)
            if key not in requirement_keys:
                requirement_keys.add(key)
                requirements.append(requirement)
    if knowledge_codes:
        repaired["knowledge_codes"] = knowledge_codes
    if requirements:
        repaired["answer_requirements"] = requirements
        repaired["total_marks"] = None
    elif not exact_top_level:
        totals = [int(total) for item in items if (total := item.get("total_marks")) is not None]
        repaired["total_marks"] = max(totals, default=None)
    return repaired


def _apply_question_repair_plan(
    items: list[dict[str, Any]],
    plan: _QuestionRepairPlan,
) -> list[dict[str, Any]]:
    indexes = [index for group in plan.groups for index in group.candidate_indexes]
    if sorted(indexes) != list(range(len(items))):
        raise ValueError("结构修复模型必须将每个候选题恰好使用一次")

    group_identities: set[str] = set()
    repaired: list[dict[str, Any]] = []
    for group in plan.groups:
        compact, canonical, _is_top_level = _question_number_identity(group.number)
        identity = canonical or compact
        if not identity or identity in group_identities:
            raise ValueError(f"结构修复模型返回了重复或无效的顶层题号：{group.number}")
        group_identities.add(identity)
        repaired.append(
            _combine_repair_group([items[index] for index in group.candidate_indexes], group)
        )
    return repaired


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
        structured_model: StructuredModelPort | None = None,
    ):
        self.settings = settings
        self.subject = subject
        self.knowledge_repository = knowledge_repository
        self.rag = rag or RagService(settings, subject, knowledge_repository)
        self.splitter = splitter
        self.parser = parser or upload_to_markdown
        self.catalog_loader = catalog_loader or self._load_catalog
        self.structured_model = structured_model

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
        *,
        load_checkpoint: SplitCheckpointLoader | None = None,
        save_checkpoint: SplitCheckpointSaver | None = None,
    ) -> list[dict[str, Any]]:
        del catalog

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

Set `requires_visual_context` to true only when solving the question depends on a
printed figure, diagram, graph, chart, plot, shaded region, or other spatial visual
information. It must be false for text-only probability/algebra questions even though
their source PDF pages are available.
Extract an `answer_requirements` item for every visible subpart, or one item labelled
`whole` when there are no subparts. Preserve the printed subpart label and marks.
`answer_kind` must be one of text, numeric, expression, proof, table, math_plot,
math_diagram, economics_diagram, image. Copy an explicit accuracy instruction and required units.
Set `required_tool` only when the candidate must create that answer artifact:
math_plot for coordinate/statistical plots, math_diagram for exact geometry or other
mathematical vector diagrams, economics_diagram for a required economics graph or
diagram, and image_generate only for a genuinely pictorial response. Merely
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
      ]
    }}
  ]
}}

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

        batches = _split_markdown_batches(
            markdown,
            max_chars=self.settings.paper_split_max_chars,
        )
        completed: dict[int, list[dict[str, Any]]] = {}
        pending: list[tuple[int, str, str]] = []
        for batch_index, batch in enumerate(batches):
            digest = hashlib.sha256(
                json.dumps(
                    {
                        "contract": SPLIT_CONTRACT_VERSION,
                        "model": self.settings.paper_split_model,
                        "reasoning_effort": self.settings.paper_split_reasoning_effort,
                        "markdown": batch,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
            ).hexdigest()
            cached = load_checkpoint(batch_index, digest) if load_checkpoint else None
            if cached is None:
                pending.append((batch_index, digest, batch))
            else:
                completed[batch_index] = cached

        first_error: Exception | None = None
        if pending:
            with ThreadPoolExecutor(
                max_workers=min(self.settings.paper_split_concurrency, len(pending))
            ) as executor:
                futures = {
                    executor.submit(split_batch, batch): (
                        batch_index,
                        digest,
                        time.monotonic(),
                    )
                    for batch_index, digest, batch in pending
                }
                for future in as_completed(futures):
                    batch_index, digest, batch_started = futures[future]
                    try:
                        questions = future.result()
                        completed[batch_index] = questions
                        if save_checkpoint:
                            save_checkpoint(
                                batch_index,
                                len(batches),
                                digest,
                                questions,
                                (time.monotonic() - batch_started) * 1000,
                            )
                    except Exception as error:
                        first_error = first_error or error
        if first_error is not None:
            raise first_error

        extracted = [
            item for batch_index in range(len(batches)) for item in completed.get(batch_index, [])
        ]
        return _merge_split_questions(extracted)

    @staticmethod
    def _cited_knowledge_codes(
        answer_markdown: str,
        citations: list[Citation],
        catalog_by_code: dict[str, dict[str, Any]],
    ) -> list[str]:
        codes: list[str] = []
        for citation_id in citation_ids_in_markdown(answer_markdown):
            citation_index = int(citation_id.removeprefix("S")) - 1
            if not 0 <= citation_index < len(citations):
                continue
            code = citations[citation_index].knowledge_code
            if code and code in catalog_by_code and code not in codes:
                codes.append(code)
                if len(codes) == 4:
                    break
        return codes

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
            related = [citation for citation in answer_citations if citation.knowledge_code == code]
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
        ledger: AgentRunLedger | None = None,
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
        input_codes = [str(code) for code in raw_codes] if isinstance(raw_codes, list) else []
        catalog_by_code = {point["code"]: point for point in catalog}
        input_codes = [code for code in input_codes if code in catalog_by_code]
        knowledge_context = "\n".join(
            f"- {code}: {catalog_by_code[code]['title']} "
            f"{catalog_by_code[code]['features'].get('description', '')}"
            for code in input_codes
        )
        request_parts = [
            (
                "Solve the following examination question completely. Show all necessary "
                "mathematical working. If the requested answer includes a sketch or "
                "construction, include a diagram."
            ),
            question,
        ]
        if knowledge_context:
            request_parts.insert(1, f"Relevant knowledge:\n{knowledge_context}")
        source_types: list[str] = []
        rag_options: dict[str, Any] = {
            "question_images": question_images,
            "question_number": number,
            "question_spec": question_spec,
            "visual_request_text": question,
            "event_sink": event_sink,
        }
        if ledger is not None:
            rag_options["ledger"] = ledger
        response = self.rag.ask(
            AskRequest(
                question="\n\n".join(request_parts),
                subject_code=self.subject.subject_code,
                unit_code=unit_code,
                pair_key=pair_key,
                authority_tiers=[
                    "official",
                    "licensed_core",
                    "licensed",
                    "supplementary",
                ],
                source_types=source_types,
                top_k=6,
            ),
            **rag_options,
        )
        codes = self._cited_knowledge_codes(
            response.answer_markdown,
            response.citations,
            catalog_by_code,
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
        return self._split_questions(
            markdown,
            unit_code=unit_code,
        )

    def split_questions_checkpointed(
        self,
        markdown: str,
        *,
        unit_code: str | None = None,
        source_markdown: str | None = None,
        load_checkpoint: SplitCheckpointLoader,
        save_checkpoint: SplitCheckpointSaver,
    ) -> list[dict[str, Any]]:
        """Split a paper in bounded batches and reuse only digest-matched results."""

        return self._split_questions(
            markdown,
            unit_code=unit_code,
            source_markdown=source_markdown,
            load_checkpoint=load_checkpoint,
            save_checkpoint=save_checkpoint,
        )

    def _repair_question_structure(
        self,
        source_markdown: str,
        items: list[dict[str, Any]],
        unresolved_numbers: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        excerpt_limit = max(800, min(3_000, 80_000 // len(items)))
        candidates = [
            {
                "candidate_index": index,
                "number": str(item.get("number", "?")),
                "question_excerpt": str(item.get("question_markdown", ""))[:excerpt_limit],
                "answer_requirements": item.get("answer_requirements") or [],
            }
            for index, item in enumerate(items)
        ]
        if len(source_markdown) > 60_000:
            source_excerpt = (
                source_markdown[:30_000]
                + "\n\n[... trusted source middle omitted ...]\n\n"
                + source_markdown[-30_000:]
            )
        else:
            source_excerpt = source_markdown
        task = StructuredTask(
            system_prompt=(
                "Repair only the grouping and physical order of extracted examination-question "
                "candidates. Return one group per top-level question in trusted source order. "
                "Group duplicate candidates and subquestion fragments under their top-level "
                "question. Use every candidate_index exactly once. Keep each group's number "
                "within the number family present in that group's candidates. Do not solve, "
                "rewrite, discard, or add questions, and do not infer source page numbers."
            ),
            user_content=json.dumps(
                {
                    "unresolved_numbers": unresolved_numbers,
                    "trusted_source_excerpt": source_excerpt,
                    "candidates": candidates,
                },
                ensure_ascii=False,
            ),
        )
        model = self.structured_model
        if model is None:
            model = _build_question_repair_model(self.settings)
            self.structured_model = model
        plan = StructuredTaskRunner(model).run(
            task,
            _QuestionRepairPlan,
            timeout=self.settings.paper_split_timeout,
        )
        repaired = _apply_question_repair_plan(items, plan)
        for item in repaired:
            spec = question_spec_from_item(item)
            item["answer_requirements"] = [part.model_dump(mode="json") for part in spec.subparts]
            item["total_marks"] = spec.total_marks
        return repaired

    def _split_questions(
        self,
        markdown: str,
        *,
        unit_code: str | None,
        source_markdown: str | None = None,
        load_checkpoint: SplitCheckpointLoader | None = None,
        save_checkpoint: SplitCheckpointSaver | None = None,
    ) -> list[dict[str, Any]]:
        if len(markdown.strip()) < 20:
            raise ValueError("解析后的试卷内容过短，无法识别题目")
        catalog = self._catalog(unit_code)
        if self.splitter is None:
            questions = self._split_with_llm(
                markdown,
                catalog,
                load_checkpoint=load_checkpoint,
                save_checkpoint=save_checkpoint,
            )
        else:
            questions = self.splitter(markdown, catalog)
        normalized = [item for item in questions if str(item.get("question_markdown", "")).strip()]
        if not normalized:
            raise ValueError("没有识别到顶层题目，请检查试卷内容或 MinerU 解析结果")
        for item in normalized:
            spec = question_spec_from_item(item)
            item["answer_requirements"] = [part.model_dump(mode="json") for part in spec.subparts]
            item["total_marks"] = spec.total_marks
        trusted_source = source_markdown or markdown
        try:
            return reconcile_question_source_pages(trusted_source, normalized)
        except QuestionSourcePageResolutionError as source_error:
            try:
                repaired = self._repair_question_structure(
                    trusted_source,
                    normalized,
                    source_error.unresolved_numbers,
                )
            except Exception as repair_error:
                raise ValueError(f"{source_error}；结构修复失败：{repair_error}") from repair_error
            return reconcile_question_source_pages(trusted_source, repaired)

    def answer_question(
        self,
        item: dict[str, Any],
        *,
        unit_code: str | None = None,
        pair_key: str | None = None,
        event_sink: AgentEventSink | None = None,
        ledger: AgentRunLedger | None = None,
    ) -> PaperQuestionAnswer:
        return self._answer_one(
            item,
            self._catalog(unit_code),
            unit_code,
            pair_key,
            event_sink,
            ledger,
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
