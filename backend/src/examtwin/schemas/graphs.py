from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from examtwin.schemas.base import SerializedResponse


class GraphEvidence(SerializedResponse):
    block_id: str | None = None
    document_id: str | None = None
    page: int | None = None
    section: str | None = None
    quote: str = ""


class GraphNodeResponse(SerializedResponse):
    id: str
    stable_key: str
    code: str
    title: str
    description: str
    node_type: str
    aliases: list[str] = Field(default_factory=list)
    parent_key: str | None = None
    unit_code: str = ""
    evidence: list[GraphEvidence] = Field(default_factory=list)
    confidence: float
    review_status: str
    metadata: dict = Field(default_factory=dict)


class GraphEdgeResponse(SerializedResponse):
    id: str
    source_key: str
    target_key: str
    relation_type: str
    evidence: list[GraphEvidence] = Field(default_factory=list)
    confidence: float
    review_status: str


class GraphVersionResponse(SerializedResponse):
    id: str
    subject_id: str
    knowledge_base_version_id: str | None = None
    version_number: int
    status: str
    source_hash: str
    model_name: str | None = None
    prompt_version: str
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    nodes: list[GraphNodeResponse] = Field(default_factory=list)
    edges: list[GraphEdgeResponse] = Field(default_factory=list)


class GraphVersionSummary(SerializedResponse):
    id: str
    subject_id: str
    knowledge_base_version_id: str | None = None
    version_number: int
    status: Literal["draft", "published", "failed"]
    model_name: str | None = None
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None


class BuildGraphRequest(BaseModel):
    knowledge_base_version_id: str


class ReviewGraphNodeRequest(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=180)
    description: str | None = Field(default=None, min_length=2, max_length=1200)
    node_type: Literal["concept", "subconcept", "formula", "term"] | None = None
    aliases: list[str] | None = None
    parent_key: str | None = None
    review_status: Literal["accepted", "rejected"]


class ReviewGraphEdgeRequest(BaseModel):
    relation_type: (
        Literal["contains", "prerequisite_of", "applies_to", "equivalent_to", "related_to"] | None
    ) = None
    review_status: Literal["accepted", "rejected"]


class ReviewAllRequest(BaseModel):
    review_status: Literal["accepted", "rejected"]
