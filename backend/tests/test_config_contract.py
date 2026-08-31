import pytest
from examtwin.platform.config import PROJECT_ROOT, Settings
from examtwin.platform.config_contract import (
    OPTIONAL_NON_SETTINGS_ENV_KEYS,
    audit_environment_contract,
)
from pydantic import ValidationError


def test_environment_files_match_the_runtime_contract() -> None:
    assert audit_environment_contract().errors == []


def test_frontend_only_environment_keys_are_documented_optional_overrides() -> None:
    audit = audit_environment_contract()
    example = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")

    assert OPTIONAL_NON_SETTINGS_ENV_KEYS.isdisjoint(audit.expected_keys)
    assert all(f"{name}=" in example for name in OPTIONAL_NON_SETTINGS_ENV_KEYS)
    assert audit.errors == []


def test_subject_bootstrap_settings_are_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "SUBJECT_PACK",
        "QDRANT_COLLECTION",
        "QDRANT_COLLECTION_ALIAS",
        "CORPUS_ROOT",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValidationError, match="subject_pack"):
        Settings()


def test_model_provider_route_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LITELLM_PROVIDER", raising=False)

    with pytest.raises(ValidationError, match="litellm_provider"):
        Settings()


def test_provider_base_urls_are_normalized_once() -> None:
    settings = Settings(
        llm_base_url="https://models.invalid/v1/",
        retrieval_base_url="https://retrieval.invalid/v1/",
    )

    assert settings.llm_base_url == "https://models.invalid/v1"
    assert settings.retrieval_base_url == "https://retrieval.invalid/v1"


def test_remote_s3_rejects_development_credentials() -> None:
    with pytest.raises(ValidationError, match="must override"):
        Settings(
            app_env="production",
            object_store_backend="s3",
            object_store_endpoint_url="https://objects.example.test",
        )


def test_loopback_development_s3_accepts_documented_credentials() -> None:
    settings = Settings(
        app_env="development",
        object_store_backend="s3",
        object_store_endpoint_url="http://127.0.0.1:8333",
    )
    assert settings.object_store_backend == "s3"
