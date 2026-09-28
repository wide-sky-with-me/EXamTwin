from __future__ import annotations

import pytest
from examtwin.platform.config import Settings
from examtwin.platform.config_contract import seed_example_environment


def test_schema_export_environment_bootstraps_settings_without_local_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    setting_names = [name.upper() for name in Settings.model_fields]
    for name in setting_names:
        monkeypatch.delenv(name, raising=False)

    seed_example_environment()
    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.subject_pack == "oxfordaqa-mathematics-9660"
    assert settings.llm_model == "gpt-6-sol"
    assert settings.llm_reasoning_effort == "low"
    assert settings.grading_reasoning_effort == "medium"
    assert settings.grading_model == "gpt-6-sol"
    assert settings.paper_split_model == "gpt-6-luna"
    assert settings.paper_vision_model == "gpt-6-sol"
    assert settings.image_generation_model == "gpt-image-2.5-flare"
    assert settings.retrieval_base_url == "https://api.siliconflow.cn/v1"
