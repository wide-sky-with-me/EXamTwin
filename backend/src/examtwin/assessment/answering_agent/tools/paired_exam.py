from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import quote

import pymupdf
from llama_index.core.tools import BaseTool, FunctionTool

from examtwin.assessment.answering_agent.blocking import run_blocking_bounded
from examtwin.assessment.answering_agent.contracts import AgentRunContext, QuestionImage
from examtwin.assessment.answering_agent.tools.question_vision import QuestionVisionProvider
from examtwin.contracts.evidence import Citation
from examtwin.knowledge.public import source_context
from examtwin.platform.config import Settings
from examtwin.platform.storage import ManagedObjectStore


class PairedExamReader(Protocol):
    def exact_pair_documents(self, pair_key: str, limit: int = 4) -> list[dict[str, Any]]: ...

    def get(self, document_id: str) -> dict[str, Any] | None: ...


_EXTRACT_LABEL = re.compile(r"\bextract\s+([A-Z])\b", re.IGNORECASE)


def _source_pdf_path(raw_path: str, corpus_root: Path) -> Path | None:
    source = Path(raw_path)
    if source.is_file():
        return source.resolve()
    root = corpus_root.resolve()
    matching_roots = [index for index, part in enumerate(source.parts) if part == root.name]
    if not matching_roots:
        return None
    candidate = root.joinpath(*source.parts[matching_roots[-1] + 1 :]).resolve()
    return candidate if candidate.is_relative_to(root) and candidate.is_file() else None


def _render_referenced_insert_pages(
    source_path: Path,
    question: str,
) -> tuple[QuestionImage, ...]:
    labels = tuple(dict.fromkeys(label.upper() for label in _EXTRACT_LABEL.findall(question)))
    if not labels:
        return ()
    images: list[QuestionImage] = []
    with pymupdf.open(source_path) as document:
        page_text = [cast(str, page.get_text()).casefold() for page in document]
        selected: set[int] = set()
        for label in labels:
            needle = f"extract {label}".casefold()
            matches = [index for index, text in enumerate(page_text) if needle in text]
            if matches:
                selected.add(matches[-1])
        for page_index in sorted(selected):
            pixmap = document[page_index].get_pixmap(
                matrix=pymupdf.Matrix(2, 2),
                alpha=False,
            )
            images.append(
                QuestionImage(
                    page_number=page_index + 1,
                    content=pixmap.tobytes("jpeg"),
                    media_type="image/jpeg",
                )
            )
    return tuple(images)


def _referenced_insert_text(source_path: Path, question: str) -> str:
    labels = tuple(dict.fromkeys(label.upper() for label in _EXTRACT_LABEL.findall(question)))
    if not labels:
        return ""
    sections: list[str] = []
    with pymupdf.open(source_path) as document:
        page_text = [cast(str, page.get_text()).strip() for page in document]
        folded = [text.casefold() for text in page_text]
        selected_pages: set[int] = set()
        for label in labels:
            needle = f"extract {label}".casefold()
            matches = [index for index, text in enumerate(folded) if needle in text]
            if not matches:
                continue
            page_index = matches[-1]
            if page_index in selected_pages:
                continue
            selected_pages.add(page_index)
            if page_text[page_index]:
                sections.append(
                    f"Official exact-pair insert page {page_index + 1}:\n{page_text[page_index]}"
                )
    return "\n\n".join(sections)[:8_000]


class PairedExamLookupTool:
    """Read evidence from documents with the uploaded paper's exact pair key."""

    name = "paired_exam_lookup"

    def __init__(
        self,
        documents: PairedExamReader,
        settings: Settings,
        *,
        timeout_seconds: float = 30,
        vision_provider: QuestionVisionProvider | None = None,
        object_store: ManagedObjectStore | None = None,
    ):
        self._documents = documents
        self._settings = settings
        self._timeout_seconds = timeout_seconds
        self._vision_provider = vision_provider
        self._object_store = object_store

    def bind(self, context: AgentRunContext) -> BaseTool:
        async def paired_exam_lookup() -> str:
            """Read the exact-pair source booklet or insert needed by this question."""

            pair_key = context.task.pair_key
            if not pair_key:
                return "No exact paper pair key is available for this uploaded paper."
            if context.task.source_booklet_document_id:
                frozen = self._documents.get(context.task.source_booklet_document_id)
                rows = [
                    frozen
                    for frozen in (frozen,)
                    if frozen is not None
                    and frozen.get("source_type") == "insert"
                    and frozen.get("pair_key") == pair_key
                    and frozen.get("status") == "converted"
                    and str(frozen.get("checksum") or "") == context.task.source_booklet_checksum
                    and str(frozen.get("converted_source_checksum") or "")
                    == context.task.source_booklet_checksum
                ]
            else:
                rows = [
                    row
                    for row in self._documents.exact_pair_documents(pair_key)
                    if row.get("source_type") == "insert"
                ]
            if not rows:
                return (
                    f"No converted source booklet or insert exists for exact pair {pair_key}. "
                    "Do not infer context from another examination session."
                )

            question_number = (context.task.question_number or "").strip()
            query = " ".join(
                item
                for item in (
                    f"Question {question_number}" if question_number else "",
                    context.task.question[:500],
                )
                if item
            )
            sections: list[str] = []
            for row in rows[:1]:
                source_path = (
                    self._object_store.materialize(str(row["object_key"]))
                    if self._object_store is not None and row.get("object_key")
                    else _source_pdf_path(
                        str(row["path"]),
                        self._settings.corpus_dir,
                    )
                )
                content_markdown = ""
                try:
                    result = await run_blocking_bounded(
                        source_context,
                        self._documents,
                        self._settings,
                        str(row["id"]),
                        query=query,
                        timeout=self._timeout_seconds,
                    )
                    content_markdown = result.content_markdown
                except (LookupError, TimeoutError):
                    if source_path is not None:
                        content_markdown = await run_blocking_bounded(
                            _referenced_insert_text,
                            source_path,
                            context.task.question,
                            timeout=self._timeout_seconds,
                        )
                if not content_markdown.strip():
                    continue
                visual_observation = ""
                if self._vision_provider is not None:
                    images = (
                        await run_blocking_bounded(
                            _render_referenced_insert_pages,
                            source_path,
                            context.task.question,
                            timeout=self._timeout_seconds,
                        )
                        if source_path is not None
                        else ()
                    )
                    if images:
                        try:
                            visual = await run_blocking_bounded(
                                self._vision_provider.inspect,
                                context.task.question,
                                images,
                                timeout=self._timeout_seconds,
                            )
                            visual_observation = (
                                "\n\nTrusted visual inspection of this exact-pair insert:\n"
                                f"{visual.observation}"
                            )
                        except TimeoutError:
                            visual_observation = (
                                "\n\nExact-pair visual inspection timed out; rely only on the "
                                "official extracted insert text above."
                            )
                excerpt = re.sub(r"\s+", " ", content_markdown).strip()[:1200]
                citation = Citation(
                    source=str(row["path"]),
                    document_id=str(row["id"]),
                    source_type=str(row["source_type"]),
                    authority_tier=str(row["authority_tier"]),
                    pair_key=str(row["pair_key"]),
                    excerpt=excerpt,
                    section=f"Question {question_number}" if question_number else None,
                    evidence_role="assessment",
                    content_url=(
                        f"/sources/{quote(str(row['id']), safe='')}/context?"
                        f"query={quote(query[:160])}"
                    ),
                )
                source_index = context.add_citation(citation)
                sections.append(
                    f"[S{source_index}] exact_pair={pair_key} "
                    f"source_type={row['source_type']} source={row['path']}\n"
                    f"{content_markdown[:8000]}{visual_observation}"
                )
            if not sections:
                return (
                    f"Exact-pair insert records exist for {pair_key}, but their converted "
                    "content is unavailable. Do not substitute another paper."
                )
            return "\n\n".join(sections)[:24_000]

        return FunctionTool.from_defaults(
            async_fn=paired_exam_lookup,
            name=self.name,
            description=(
                "Read the official source booklet or insert matching this uploaded paper's "
                "exact year/session/unit pair. This tool never exposes mark schemes, examiner "
                "reports, or material from another examination session."
            ),
        )
