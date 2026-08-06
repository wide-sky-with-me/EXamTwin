import pytest
from examtwin.platform.config import Settings
from examtwin.platform.config_contract import audit_environment_contract
from pydantic import ValidationError


def test_environment_files_match_the_runtime_contract() -> None:
    assert audit_environment_contract().errors == []


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
