from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from examtwin.schemas.base import SerializedResponse


class KnowledgeBaseVersionResponse(SerializedResponse):
    id: str
    knowledge_base_id: str
    version_number: int
    status: str
    alias_name: str
    collection_name: str | None = None
    vector_build_id: str | None = None
    parser_version: str
    created_at: datetime
    published_at: datetime | None = None


class KnowledgeBaseResponse(SerializedResponse):
    id: str
    subject_id: str
    name: str
    kind: Literal["core", "supplementary"]
    active_version_id: str | None = None
    active_version: KnowledgeBaseVersionResponse | None = None


class CreateSubjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=2, max_length=63)
    subject_code: str = Field(min_length=2, max_length=32)
    title: str = Field(min_length=1, max_length=200)
    board_name: str = Field(min_length=1, max_length=200)
    language: str = Field(default="en", min_length=2, max_length=16)
    capability_profile_id: str | None = None


class SourceDocumentResponse(SerializedResponse):
    id: str
    filename: str
    source_type: str
    source_role: str
    authority_tier: str
    knowledge_base_id: str | None = None
    license_confirmed: bool
    status: str
    checksum: str
    object_key: str | None = None
    page_count: int | None = None
    error: str | None = None


class KnowledgeBaseBuildResponse(SerializedResponse):
    version: KnowledgeBaseVersionResponse
    processed: int
    succeeded: int
    failed: int
    errors: list[str] = Field(default_factory=list)


class GraphEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    block_id: str | None = None
    page: int | None = None
    excerpt: str


class GraphNodeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stable_key: str = Field(min_length=1, max_length=160)
    code: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=8000)
    node_type: Literal[
        "unit", "topic", "learning_objective", "concept", "skill", "method", "formula"
    ]
    aliases: list[str] = Field(default_factory=list, max_length=50)
    parent_key: str | None = None
    unit_code: str = ""
    evidence: list[GraphEvidence] = Field(default_factory=list)
    confidence: float = Field(default=1, ge=0, le=1)
    review_status: Literal["pending", "accepted", "rejected"] = "accepted"


class GraphNodePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=8000)
    node_type: (
        Literal["unit", "topic", "learning_objective", "concept", "skill", "method", "formula"]
        | None
    ) = None
    aliases: list[str] | None = Field(default=None, max_length=50)
    parent_key: str | None = None
    unit_code: str | None = None
    evidence: list[GraphEvidence] | None = None
    review_status: Literal["pending", "accepted", "rejected"] | None = None


class GraphNodeResponse(GraphNodeInput, SerializedResponse):
    id: str
    graph_version_id: str


class GraphEdgeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_key: str
    target_key: str
    relation_type: Literal[
        "contains",
        "prerequisite_of",
        "depends_on",
        "applies_to",
        "contrasts_with",
        "equivalent_to",
    ]
    evidence: list[GraphEvidence] = Field(default_factory=list)
    confidence: float = Field(default=1, ge=0, le=1)
    review_status: Literal["pending", "accepted", "rejected"] = "accepted"


class GraphEdgeResponse(GraphEdgeInput, SerializedResponse):
    id: str
    graph_version_id: str


class GraphVersionResponse(SerializedResponse):
    id: str
    subject_id: str
    knowledge_base_version_id: str | None = None
    version_number: int
    status: str
    source_hash: str
    model_name: str | None = None
    prompt_version: str
    nodes: list[GraphNodeResponse]
    edges: list[GraphEdgeResponse]
    created_at: datetime
    published_at: datetime | None = None


class MergeNodesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_keys: list[str] = Field(min_length=1, max_length=50)


class SplitNodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[GraphNodeInput] = Field(min_length=2, max_length=20)


class GraphBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    knowledge_base_version_id: str


class CompletedPaperJobSummary(SerializedResponse):
    id: str
    filename: str
    subject_code: str
    unit_code: str | None = None
    total_questions: int
    completed_questions: int
    completed_at: datetime | None = None
