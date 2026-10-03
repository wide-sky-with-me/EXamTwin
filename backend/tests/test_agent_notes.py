from pathlib import Path

import pytest

import scripts.agent_notes as agent_notes

IMPLEMENTED = """# Agent Note: Example

Status: implemented

## Problem

Why.

## Decision

What.

## Alternatives considered

- **Other** — strongest case, then why not.

## Consequences

- Cost and benefit.
"""


def _write(root: Path, relative: str, text: str = IMPLEMENTED) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _errors(root: Path, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.setattr(agent_notes, "_baseline_manifest", lambda _root: {})
    return agent_notes.check(root)


def test_repository_notes_pass() -> None:
    assert agent_notes.check() == []


def test_valid_implemented_note_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "implemented/feature/2026-10-03-example.md")

    assert _errors(tmp_path, monkeypatch) == []


@pytest.mark.parametrize(
    ("relative", "message"),
    [
        ("implemented/refactor/2026-10-03-example.md", "unknown class"),
        ("implemented/feature/example.md", "yyyy-mm-dd-topic.md"),
        ("implemented/2026-10-03-example.md", "expected implemented/<class>"),
        ("drafts/feature/2026-10-03-example.md", "unknown lifecycle"),
        ("implemented/feature/INDEX.md", "INDEX.md"),
    ],
)
def test_tree_rejects_unknown_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str, message: str
) -> None:
    _write(tmp_path, relative)

    assert any(message in error for error in _errors(tmp_path, monkeypatch))


def test_status_must_match_lifecycle_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, "proposed/feature/2026-10-03-example.md")

    assert any("does not match folder" in error for error in _errors(tmp_path, monkeypatch))


def test_implemented_note_requires_alternatives_and_rejects_plan_headings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = IMPLEMENTED.replace("## Alternatives considered", "## Acceptance criteria")
    _write(tmp_path, "implemented/feature/2026-10-03-example.md", text)

    errors = _errors(tmp_path, monkeypatch)

    assert any("missing ## Alternatives considered" in error for error in errors)
    assert any("proposal heading" in error for error in errors)


def test_rejected_status_needs_reason(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    text = IMPLEMENTED.replace("Status: implemented", "Status: rejected").replace(
        "## Decision", "## Proposal"
    )
    _write(tmp_path, "rejected/feature/2026-10-03-example.md", text)

    assert any("rejected — <reason>" in error for error in _errors(tmp_path, monkeypatch))


def test_broken_relative_link_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(
        tmp_path,
        "implemented/feature/2026-10-03-example.md",
        IMPLEMENTED + "\n[gone](../architecture/2026-01-01-missing.md)\n",
    )

    assert any("broken relative link" in error for error in _errors(tmp_path, monkeypatch))


def test_archive_seals_note_and_detects_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = _write(tmp_path, "implemented/architecture/2026-01-01-old.md")
    new = _write(tmp_path, "implemented/architecture/2026-10-03-new.md")
    _write(
        tmp_path,
        "implemented/feature/2026-10-03-linker.md",
        IMPLEMENTED + "\n[old](../architecture/2026-01-01-old.md)\n",
    )

    inbound = agent_notes.archive(old, new, root=tmp_path)

    archived = tmp_path / "archived/architecture/2026-01-01-old.md"
    assert not old.exists()
    assert archived.read_text(encoding="utf-8").split("\n")[3].startswith("Archived: ")
    assert inbound == [
        "implemented/feature/2026-10-03-linker.md -> ../architecture/2026-01-01-old.md"
    ]
    assert "../../archived/architecture/2026-01-01-old.md" in new.read_text(encoding="utf-8")
    assert agent_notes.check_archive(tmp_path, compare_baseline=False) == []

    archived.write_text(archived.read_text(encoding="utf-8") + "edit\n", encoding="utf-8")
    assert any(
        "content changed" in error
        for error in agent_notes.check_archive(tmp_path, compare_baseline=False)
    )


def test_removed_seal_fails_against_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_notes, "_baseline_manifest", lambda _root: {"feature/x.md": "abc"})

    assert any("changed or removed" in error for error in agent_notes.check_archive(tmp_path))
