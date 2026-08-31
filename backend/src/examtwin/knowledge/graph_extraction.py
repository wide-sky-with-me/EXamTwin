from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from examtwin.knowledge.document_block_repository import DocumentBlockRepository
from examtwin.knowledge.graph_repository import GraphRepository
from examtwin.platform.agent_runtime.model import HarnessMessage
from examtwin.platform.agent_runtime.structured import StructuredModelPort
from examtwin.platform.config import Settings
from examtwin.platform.structured_model import LiteLLMStructuredModel
from examtwin.subjects.public import SubjectContext, WorkspaceRepository

PROMPT_VERSION = "concept-extraction-v1"
NODE_TYPES = ("concept", "subconcept", "formula", "term")
RELATION_TYPES = ("contains", "prerequisite_of", "applies_to", "equivalent_to", "related_to")


class ExtractedNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=2, max_length=180)
    description: str = Field(min_length=2, max_length=1200)
    node_type: Literal["concept", "subconcept", "formula", "term"]
    aliases: list[str] = Field(default_factory=list, max_length=12)
    parent_title: str | None = Field(default=None, max_length=180)
    evidence_block_id: str = Field(min_length=1)
    evidence_quote: str = Field(min_length=2, max_length=800)
    confidence: float = Field(ge=0, le=1)


class ExtractedRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_title: str = Field(min_length=2, max_length=180)
    target_title: str = Field(min_length=2, max_length=180)
    relation_type: Literal[
        "contains", "prerequisite_of", "applies_to", "equivalent_to", "related_to"
    ]
    evidence_block_id: str = Field(min_length=1)
    evidence_quote: str = Field(min_length=2, max_length=800)
    confidence: float = Field(ge=0, le=1)


class GraphExtractionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[ExtractedNode] = Field(default_factory=list, max_length=80)
    relations: list[ExtractedRelation] = Field(default_factory=list, max_length=120)


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _stable_key(node_type: str, title: str) -> str:
    digest = hashlib.sha1(f"{node_type}\0{title.casefold()}".encode()).hexdigest()[:16]
    return f"{node_type}:{_normalize(title)[:48]}:{digest}"


def _batches(blocks: Sequence[dict], max_chars: int) -> list[list[dict]]:
    batches: list[list[dict]] = []
    current: list[dict] = []
    size = 0
    for block in blocks:
        block_size = len(str(block["content"]))
        if current and size + block_size > max_chars:
            batches.append(current)
            current = []
            size = 0
        current.append(block)
        size += block_size
    if current:
        batches.append(current)
    return batches


class KnowledgeGraphBuildService:
    """Extract reviewable graph drafts from one immutable knowledge-base version."""

    def __init__(
        self,
        settings: Settings,
        subject: SubjectContext,
        workspaces: WorkspaceRepository,
        blocks: DocumentBlockRepository,
        graphs: GraphRepository,
        *,
        model: StructuredModelPort | None = None,
    ) -> None:
        self.settings = settings
        self.subject = subject
        self.workspaces = workspaces
        self.blocks = blocks
        self.graphs = graphs
        if model is not None:
            self.model = model
        else:
            key = settings.llm_api_key
            if key is None:
                raise ValueError("知识图谱抽取需要 LLM_API_KEY")
            self.model = LiteLLMStructuredModel(
                model=settings.knowledge_graph_model,
                provider=settings.litellm_provider,
                api_base=settings.llm_base_url,
                api_key=key.get_secret_value(),
                reasoning_effort=settings.knowledge_graph_reasoning_effort,
            )

    def build(self, knowledge_base_version_id: str) -> dict:
        version = self.workspaces.require_version(knowledge_base_version_id)
        base = self.workspaces.require_base(str(version["knowledge_base_id"]))
        if base["subject_id"] != self.subject.id:
            raise ValueError("知识库版本不属于当前科目")
        if version["status"] != "published":
            raise ValueError("只能从已发布知识库版本生成知识图谱")
        blocks = self.blocks.list_for_version(
            knowledge_base_version_id,
            block_kinds=("section",),
            limit=self.settings.knowledge_graph_max_blocks,
        )
        if not blocks:
            raise ValueError("知识库版本没有可用于图谱抽取的层级文档块")
        source_hash = hashlib.sha256(
            json.dumps(
                [(block["id"], block["content_hash"]) for block in blocks],
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        version_id = self.graphs.create_version(
            subject_id=self.subject.id,
            knowledge_base_version_id=knowledge_base_version_id,
            source_hash=source_hash,
            model_name=self.settings.knowledge_graph_model,
            prompt_version=PROMPT_VERSION,
        )
        try:
            extracted_nodes: list[ExtractedNode] = []
            extracted_relations: list[ExtractedRelation] = []
            for batch in _batches(blocks, self.settings.knowledge_graph_batch_chars):
                block_text = "\n\n".join(
                    (
                        f"[BLOCK {block['id']}] source_document={block['document_id']} "
                        f"page={block.get('page')} section={block.get('section') or '-'}\n"
                        f"{str(block['content'])[: self.settings.knowledge_graph_block_max_chars]}"
                    )
                    for block in batch
                )
                result = self.model.complete(
                    [
                        HarnessMessage(
                            role="system",
                            content=(
                                "Extract a conservative, reviewable subject knowledge graph "
                                "from the supplied source blocks. Nodes must be concepts, "
                                "subconcepts, formulas, or terms. Every node and relation must "
                                "cite one supplied block ID and a verbatim supporting quote. "
                                "Never infer prerequisite or equivalence without explicit "
                                "textual evidence. Use contains for documented hierarchy, "
                                "applies_to for a stated use, and related_to only for an "
                                "explicit relation. Do not extract assessment logistics."
                            ),
                        ),
                        HarnessMessage(role="user", content=block_text),
                    ],
                    GraphExtractionBatch,
                    timeout=self.settings.knowledge_graph_timeout,
                )
                extracted_nodes.extend(result.nodes)
                extracted_relations.extend(result.relations)
            node_rows, edge_rows = self._rows(blocks, extracted_nodes, extracted_relations)
            self.graphs.store_draft(version_id, nodes=node_rows, edges=edge_rows)
            return self.graphs.get(version_id)
        except Exception:
            self.graphs.fail_version(version_id)
            raise

    def _rows(
        self,
        blocks: Sequence[dict],
        nodes: Sequence[ExtractedNode],
        relations: Sequence[ExtractedRelation],
    ) -> tuple[list[dict], list[dict]]:
        blocks_by_id = {str(block["id"]): block for block in blocks}
        root_key = f"subject:{self.subject.id}"
        node_rows: list[dict] = [
            {
                "stable_key": root_key,
                "code": "ROOT",
                "title": self.subject.pack.title,
                "description": f"Knowledge graph root for {self.subject.pack.title}",
                "node_type": "subject",
                "aliases_json": "[]",
                "parent_key": None,
                "unit_code": "",
                "evidence_json": "[]",
                "confidence": 1.0,
                "review_status": "accepted",
                "metadata_json": json.dumps({"system_node": True}),
            }
        ]
        by_title: dict[str, str] = {}
        evidence_by_title: dict[str, list[dict]] = {}
        chosen: dict[str, ExtractedNode] = {}
        for node in nodes:
            block = blocks_by_id.get(node.evidence_block_id)
            if block is None:
                continue
            normalized = node.title.casefold().strip()
            existing = chosen.get(normalized)
            if existing is None or node.confidence > existing.confidence:
                chosen[normalized] = node
            evidence_by_title.setdefault(normalized, []).append(
                {
                    "block_id": node.evidence_block_id,
                    "document_id": block["document_id"],
                    "page": block.get("page"),
                    "section": block.get("section"),
                    "quote": node.evidence_quote,
                }
            )
        for index, (normalized, node) in enumerate(chosen.items(), start=1):
            key = _stable_key(node.node_type, node.title)
            by_title[normalized] = key
            node_rows.append(
                {
                    "stable_key": key,
                    "code": f"KG-{index:04d}",
                    "title": node.title.strip(),
                    "description": node.description.strip(),
                    "node_type": node.node_type,
                    "aliases_json": json.dumps(
                        list(
                            dict.fromkeys(alias.strip() for alias in node.aliases if alias.strip())
                        ),
                        ensure_ascii=False,
                    ),
                    "parent_key": None,
                    "unit_code": "",
                    "evidence_json": json.dumps(evidence_by_title[normalized], ensure_ascii=False),
                    "confidence": node.confidence,
                    "review_status": "pending",
                    "metadata_json": "{}",
                }
            )
        rows_by_key = {row["stable_key"]: row for row in node_rows}
        edge_rows: list[dict] = []
        edge_keys: set[tuple[str, str, str]] = set()
        for normalized, node in chosen.items():
            source_key = by_title[normalized]
            parent_key = (
                by_title.get(node.parent_title.casefold().strip()) if node.parent_title else None
            )
            parent_key = parent_key or root_key
            rows_by_key[source_key]["parent_key"] = parent_key
            relation_key = (parent_key, source_key, "contains")
            if relation_key not in edge_keys:
                edge_keys.add(relation_key)
                edge_rows.append(
                    {
                        "source_key": parent_key,
                        "target_key": source_key,
                        "relation_type": "contains",
                        "evidence_json": rows_by_key[source_key]["evidence_json"],
                        "confidence": node.confidence,
                        "review_status": "pending",
                    }
                )
        for relation in relations:
            source_key = by_title.get(relation.source_title.casefold().strip())
            target_key = by_title.get(relation.target_title.casefold().strip())
            block = blocks_by_id.get(relation.evidence_block_id)
            if (
                source_key is None
                or target_key is None
                or block is None
                or source_key == target_key
            ):
                continue
            relation_key = (source_key, target_key, relation.relation_type)
            if relation_key in edge_keys:
                continue
            edge_keys.add(relation_key)
            edge_rows.append(
                {
                    "source_key": source_key,
                    "target_key": target_key,
                    "relation_type": relation.relation_type,
                    "evidence_json": json.dumps(
                        [
                            {
                                "block_id": relation.evidence_block_id,
                                "document_id": block["document_id"],
                                "page": block.get("page"),
                                "section": block.get("section"),
                                "quote": relation.evidence_quote,
                            }
                        ],
                        ensure_ascii=False,
                    ),
                    "confidence": relation.confidence,
                    "review_status": "pending",
                }
            )
        return node_rows, edge_rows
