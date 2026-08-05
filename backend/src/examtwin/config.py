from __future__ import annotations

import ipaddress
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ReasoningEffort = Literal["none", "low", "medium", "high", "xhigh", "max"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ExamTwin"
    app_env: str = "development"
    local_access_only: bool = True
    api_prefix: str = "/api/v1"
    subject_pack: str = "oxfordaqa-mathematics-9660"
    subject_packages_root: Path = Path("subject-packs")

    mineru_token: SecretStr | None = None
    mineru_mode: str = "precision"
    mineru_language: str = "en"

    openai_compat_base_url: str = "https://api.openai.com/v1"
    openai_compat_api_key: SecretStr | None = None
    llm_model: str = "gpt-5.6-sol"
    llm_reasoning_effort: ReasoningEffort = "medium"
    knowledge_difficulty_model: str = "gpt-5.6-luna"
    knowledge_difficulty_reasoning_effort: ReasoningEffort = "none"
    knowledge_difficulty_timeout: int = Field(default=120, ge=30, le=300)
    knowledge_difficulty_batch_size: int = Field(default=20, ge=1, le=50)
    grading_model: str = "gpt-5.6-sol"
    grading_reasoning_effort: ReasoningEffort = "medium"
    grading_timeout: int = Field(default=120, ge=30, le=300)
    paper_split_model: str = "gpt-5.6-luna"
    paper_split_reasoning_effort: ReasoningEffort = "none"
    paper_split_timeout: int = Field(default=90, ge=30, le=300)
    paper_split_max_chars: int = Field(default=4_000, ge=2_500, le=60_000)
    paper_split_concurrency: int = Field(default=2, ge=1, le=4)
    paper_vision_enabled: bool = True
    paper_vision_model: str = "gpt-5.6-terra"
    paper_vision_reasoning_effort: ReasoningEffort = "low"
    paper_vision_timeout: int = Field(default=120, ge=30, le=300)
    paper_vision_max_attempts: int = Field(default=3, ge=1, le=5)
    paper_vision_retry_delay_seconds: float = Field(default=2, ge=0, le=60)
    paper_vision_min_confidence: float = Field(default=0.7, ge=0, le=1)
    paper_vision_concurrency: int = Field(default=2, ge=1, le=4)
    image_generation_enabled: bool = False
    image_generation_base_url: str | None = None
    image_generation_api_key: SecretStr | None = None
    image_generation_model: str = "gpt-image-2"
    image_generation_timeout: int = Field(default=120, ge=30, le=300)
    image_generation_max_attempts: int = Field(default=2, ge=1, le=3)
    image_generation_max_output_bytes: int = Field(
        default=8 * 1024 * 1024,
        ge=64 * 1024,
        le=32 * 1024 * 1024,
    )

    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    siliconflow_api_key: SecretStr | None = None
    embedding_model: str = "Qwen/Qwen3-Embedding-8B"
    rerank_model: str = "Qwen/Qwen3-Reranker-8B"
    embedding_timeout: int = Field(default=25, ge=5, le=120)
    rerank_timeout: int = Field(default=30, ge=5, le=120)

    database_url: str = "postgresql://examtwin:examtwin_dev@localhost:55432/examtwin"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "examtwin_9660"
    qdrant_collection_alias: str = "examtwin_9660_live"
    corpus_root: Path = Path("data/牛津AQA/数学")
    object_store_backend: Literal["local", "s3"] = "local"
    object_store_local_root: Path = Path("var")
    object_store_cache_dir: Path = Path("var/object-cache")
    object_store_endpoint_url: str = "http://127.0.0.1:8333"
    object_store_bucket: str = "examtwin"
    object_store_region: str = "us-east-1"
    object_store_access_key: SecretStr = SecretStr("examtwin")
    object_store_secret_key: SecretStr = SecretStr("examtwin_dev_secret")
    paper_object_retention_days: int = Field(default=30, ge=1, le=3650)
    answer_artifact_retention_days: int = Field(default=30, ge=1, le=3650)
    storage_gc_batch_size: int = Field(default=200, ge=1, le=5000)
    storage_gc_interval_seconds: int = Field(default=3600, ge=60, le=86400)
    paper_chunk_pages: int = Field(default=5, ge=1, le=20)
    paper_lease_seconds: int = Field(default=60, ge=30, le=3600)
    paper_worker_poll_seconds: float = Field(default=2.0, ge=0.2, le=60)
    paper_mineru_timeout: int = Field(default=600, ge=60, le=1800)
    paper_question_max_attempts: int = Field(default=3, ge=1, le=5)
    paper_question_retry_delay_seconds: float = Field(default=2, ge=0, le=60)
    paper_question_concurrency: int = Field(default=4, ge=1, le=8)
    paper_question_image_max_pages: int = Field(default=4, ge=1, le=10)
    paper_question_image_max_total_bytes: int = Field(
        default=12 * 1024 * 1024,
        ge=1024,
        le=64 * 1024 * 1024,
    )
    answer_agent_timeout: int = Field(default=300, ge=30, le=600)
    answer_agent_max_iterations: int = Field(default=16, ge=2, le=24)
    answer_agent_max_tool_calls: int = Field(default=12, ge=1, le=20)
    answer_agent_mcp_servers_json: str = "[]"
    cors_origins: str = "http://localhost:5173"

    similarity_top_k: int = Field(default=18, ge=1, le=100)
    rerank_top_n: int = Field(default=7, ge=1, le=50)
    retrieval_hybrid_alpha: float = Field(default=0.55, ge=0, le=1)
    retrieval_raw_fallback_count: int = Field(default=2, ge=0, le=5)
    retrieval_trace_enabled: bool = True
    retrieval_trace_max_rows_per_subject: int = Field(default=2_000, ge=100, le=100_000)

    @model_validator(mode="after")
    def validate_object_store_credentials(self) -> Settings:
        if self.object_store_backend != "s3":
            return self
        endpoint_host = urlparse(self.object_store_endpoint_url).hostname or ""
        try:
            local_endpoint = ipaddress.ip_address(endpoint_host).is_loopback
        except ValueError:
            local_endpoint = endpoint_host == "localhost"
        development_local = self.app_env == "development" and local_endpoint
        access_key = self.object_store_access_key.get_secret_value()
        secret_key = self.object_store_secret_key.get_secret_value()
        weak_defaults = access_key == "examtwin" or secret_key == "examtwin_dev_secret"
        if not development_local and weak_defaults:
            raise ValueError(
                "Remote or non-development S3 storage must override the development credentials"
            )
        if not access_key or not secret_key:
            raise ValueError("S3 object storage credentials must not be empty")
        return self

    def resolved(self, path: Path) -> Path:
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def subject_packages_dir(self) -> Path:
        return self.resolved(self.subject_packages_root)

    @property
    def corpus_dir(self) -> Path:
        return self.resolved(self.corpus_root)

    @property
    def markdown_dir(self) -> Path:
        return self.object_store_root / "corpus" / "md"

    @property
    def object_store_root(self) -> Path:
        return self.resolved(self.object_store_local_root)

    @property
    def object_cache_dir(self) -> Path:
        return self.resolved(self.object_store_cache_dir)

    @property
    def llm_provider_base_url(self) -> str:
        return self.openai_compat_base_url.rstrip("/")

    @property
    def llm_provider_api_key(self) -> SecretStr | None:
        return self.openai_compat_api_key

    @property
    def image_provider_base_url(self) -> str:
        return (self.image_generation_base_url or self.llm_provider_base_url).rstrip("/")

    @property
    def image_provider_api_key(self) -> SecretStr | None:
        if (
            self.image_generation_api_key is not None
            and self.image_generation_api_key.get_secret_value()
        ):
            return self.image_generation_api_key
        return self.llm_provider_api_key

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def answer_agent_mcp_servers(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.answer_agent_mcp_servers_json)
        except json.JSONDecodeError as error:
            raise ValueError("ANSWER_AGENT_MCP_SERVERS_JSON must be valid JSON") from error
        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
            raise ValueError("ANSWER_AGENT_MCP_SERVERS_JSON must be a JSON array of objects")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
