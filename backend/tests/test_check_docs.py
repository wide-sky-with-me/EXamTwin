import json
from pathlib import Path

import scripts.check_docs as check_docs


def _project(tmp_path: Path, files: dict[str, str], budgets: dict[str, object]) -> list[str]:
    for relative, text in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    budgets_path = tmp_path / "docs" / "doc-budgets.json"
    budgets_path.parent.mkdir(parents=True, exist_ok=True)
    budgets_path.write_text(json.dumps(budgets), encoding="utf-8")
    return check_docs.check(tmp_path, budgets_path)


def test_repository_documentation_passes() -> None:
    assert check_docs.check() == []


def test_units_count_cjk_characters_and_latin_words() -> None:
    assert check_docs.count_units("严格配对 pair_key uses Qdrant") == 4 + 3


def test_over_budget_and_unbudgeted_files_fail(tmp_path: Path) -> None:
    errors = _project(
        tmp_path,
        {"docs/subsystems/a.md": "一二三四五六", "docs/extra.md": "x"},
        {"globs": {"docs/subsystems/*.md": 5}},
    )

    assert any("docs/subsystems/a.md: 6 units exceeds budget 5" in error for error in errors)
    assert any("docs/extra.md: no budget" in error for error in errors)


def test_history_wording_is_rejected_outside_postmortems_and_code(tmp_path: Path) -> None:
    errors = _project(
        tmp_path,
        {
            "docs/a.md": (
                "检索不再调用外部服务。\n`不再` 作为示例词。\n现在时描述，只出现在适配层。\n"
            ),
            "docs/postmortem/b.md": "以前的实现会超时。\n",
        },
        {"globs": {"docs/*.md": 100, "docs/postmortem/*.md": 100}},
    )

    assert errors == ["docs/a.md:1: history wording '不再'; describe the current state"]


def test_broken_relative_links_fail(tmp_path: Path) -> None:
    errors = _project(
        tmp_path,
        {
            "AGENTS.md": "[ok](docs/a.md) [gone](docs/missing.md) [web](https://example.com)",
            "docs/a.md": "",
        },
        {"files": {"AGENTS.md": 100, "docs/a.md": 100}},
    )

    assert errors == ["AGENTS.md:1: broken relative link docs/missing.md"]
