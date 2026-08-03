from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    subject_code: str = "9660"
    api_contract_version: str
    capabilities: list[str]
    llm_model: str
    embedding_model: str
    rerank_model: str
    credentials: dict[str, bool]
    object_storage_backend: str


class SubjectUnitResponse(BaseModel):
    code: str
    title: str
    strand: str


class SubjectPackResponse(BaseModel):
    id: str
    subject_code: str
    title: str
    board_name: str
    units: list[SubjectUnitResponse]


class InventoryRequest(BaseModel):
    refresh: bool = True


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


class JobResult(BaseModel):
    processed: int
    succeeded: int
    failed: int
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)


class StatsResponse(BaseModel):
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
