from __future__ import annotations

import json
from pathlib import Path

import pytest
from examtwin.answering_agent.contracts import AnswerTask
from examtwin.answering_agent.prompts import compose_system_prompt
from examtwin.subject_packages import (
    DEFAULT_SUBJECT_PACKS_ROOT,
    SubjectPackageRegistry,
    get_subject_package,
)


def test_bundled_subject_packages_preserve_math_and_fail_closed_for_unreviewed_economics() -> None:
    mathematics = get_subject_package("oxfordaqa-mathematics-9660")
    economics = get_subject_package("oxfordaqa-economics-9640")

    skill = mathematics.require_skill()
    assert mathematics.pack.subject_code == "9660"
    assert skill.required_visual_tool("Sketch the curve on the axes.") == "math_plot"
    assert skill.mandatory_tool_names == ("knowledge_search",)
    assert skill.package_digest == mathematics.digest
    assert economics.pack.subject_code == "9640"
    assert economics.answering_enabled is False
    with pytest.raises(LookupError, match="has not yet been reviewed"):
        economics.require_skill()


def test_subject_package_rejects_skill_path_escape(tmp_path: Path) -> None:
    package_dir = tmp_path / "oxfordaqa-mathematics-9660"
    package_dir.mkdir()
    manifest = json.loads(
        (DEFAULT_SUBJECT_PACKS_ROOT / package_dir.name / "manifest.json").read_text("utf-8")
    )
    manifest["answering"]["instructions_file"] = "../outside.md"
    (package_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "outside.md").write_text("untrusted", encoding="utf-8")

    with pytest.raises(ValueError, match="escapes its package directory"):
        SubjectPackageRegistry.from_directory(tmp_path)


def test_prompt_composition_keeps_platform_subject_and_runtime_layers_distinct() -> None:
    skill = get_subject_package("oxfordaqa-mathematics-9660").require_skill()
    p1 = compose_system_prompt(
        skill,
        AnswerTask(subject_code="9660", unit_code="P1", question="Solve it."),
    )
    p2 = compose_system_prompt(
        skill,
        AnswerTask(subject_code="9660", unit_code="P2", question="Solve it."),
    )

    assert p1.text.index("# Platform invariants") < p1.text.index("# Installed subject policy")
    assert p1.text.index("# Installed subject policy") < p1.text.index("# Runtime task data")
    assert '"unit_code": "P1"' in p1.text
    assert p1.digest != p2.digest
