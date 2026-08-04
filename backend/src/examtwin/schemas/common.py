from __future__ import annotations

from pydantic import BaseModel, Field

from examtwin.schemas.base import SerializedResponse


class InfrastructureHealthResponse(SerializedResponse):
    postgresql: bool
    qdrant: bool
    object_storage: bool


class HealthResponse(SerializedResponse):
    status: str
    subject_code: str = "9660"
    api_contract_version: str
    capabilities: list[str]
    llm_model: str
    embedding_model: str
    rerank_model: str
    credentials: dict[str, bool]
    object_storage_backend: str
    infrastructure: InfrastructureHealthResponse


class SubjectUnitResponse(SerializedResponse):
    code: str
    title: str
    strand: str


class SubjectPackResponse(SerializedResponse):
    id: str
    version: str
    digest: str
    subject_code: str
    title: str
    board_name: str
    answering_enabled: bool
    answering_disabled_reason: str | None = None
    units: list[SubjectUnitResponse]


class InventoryRequest(BaseModel):
    refresh: bool = True


class InventoryResponse(SerializedResponse):
    scanned: int
    by_type: dict[str, int]
    exam_identity_incomplete: int
    identity_failures: dict[str, int]
    strict_pairing_ready: bool


class ConvertRequest(BaseModel):
    document_ids: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)
    authority_tiers: list[str] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1, le=1000)
    workers: int = Field(default=2, ge=1, le=8)
    force: bool = False


class IndexRequest(BaseModel):
    rebuild: bool = True
    limit: int | None = Field(default=None, ge=1, le=10000)


class JobResult(SerializedResponse):
    processed: int
    succeeded: int
    failed: int
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)


class StatsResponse(SerializedResponse):
    documents_total: int
    documents_by_type: dict[str, int]
    documents_by_status: dict[str, int]
    strict_pairs: int
    orphan_question_papers: int
    orphan_mark_schemes: int
    knowledge_points: int
    relations: int
    question_difficulty_rows: int
    pending_reviews: int
    exam_identity_incomplete: int = 0
