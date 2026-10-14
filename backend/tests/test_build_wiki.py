from pathlib import Path

import pytest

from scripts import build_wiki as wiki


def _project(root: Path) -> Path:
    files = {
        "docs/README.md": (
            "# Documentation\n\n[Architecture](architecture.md#ownership)\n"
            "[Guide](cookbook/start.md)\n[Source](../backend/main.py)\n"
            "[Backend](../backend/)\n[External](https://example.com/x)\n[Anchor](#start)\n"
        ),
        "docs/architecture.md": "# Architecture\n\n[Home](README.md)\n",
        "docs/cookbook/start.md": "# Getting started\n\n[Architecture](../architecture.md)\n",
        "docs/AGENTS.md": "# Rules\n",
        "backend/main.py": "pass\n",
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def test_pages_are_deterministic_and_links_have_correct_owners(tmp_path: Path) -> None:
    root = _project(tmp_path)
    pages = wiki.render_pages(root, ref="deadbeef")

    assert pages == wiki.render_pages(root, ref="deadbeef")
    assert set(pages) == {
        "Home.md",
        "architecture.md",
        "Guide-start.md",
        "_Sidebar.md",
        "_Footer.md",
    }
    assert "[Architecture](architecture#ownership)" in pages["Home.md"]
    assert "[Guide](Guide-start)" in pages["Home.md"]
    assert f"[Source]({wiki.REPOSITORY}/blob/deadbeef/backend/main.py)" in pages["Home.md"]
    assert f"[Backend]({wiki.REPOSITORY}/tree/deadbeef/backend)" in pages["Home.md"]
    assert "[External](https://example.com/x)" in pages["Home.md"]
    assert "[Anchor](#start)" in pages["Home.md"]
    assert "[Home](Home)" in pages["architecture.md"]
    assert "[Getting started](Guide-start)" in pages["_Sidebar.md"]
    assert "/blob/deadbeef/docs/README.md" in pages["Home.md"]


def test_link_syntax_keeps_titles_references_and_code_intact(tmp_path: Path) -> None:
    root = _project(tmp_path)
    source = root / "docs" / "README.md"
    (root / "backend" / "with space.py").write_text("pass\n", encoding="utf-8")
    text = (
        '[Guide](cookbook/start.md "A title")\n'
        "[source]: <../backend/with space.py>\n"
        "`[literal](missing.md)`\n``[literal](missing.md)``\n"
        "```md\n[literal](missing.md)\n```\n"
        "~~~~md\n[literal](missing.md)\n~~~\n[literal](missing.md)\n~~~~\n"
        "[Actual](architecture.md)\n"
    )
    pages = {page.source: page for page in wiki.discover_pages(root)}
    rendered = wiki.rewrite_links(text, source, root, pages, "main")

    assert '[Guide](Guide-start "A title")' in rendered
    assert f"[source]: {wiki.REPOSITORY}/blob/main/backend/with%20space.py" in rendered
    assert "`[literal](missing.md)`" in rendered
    assert "``[literal](missing.md)``" in rendered
    assert "```md\n[literal](missing.md)\n```" in rendered
    assert "~~~~md\n[literal](missing.md)\n~~~\n[literal](missing.md)\n~~~~" in rendered
    assert "[Actual](architecture)" in rendered


@pytest.mark.parametrize("target", ["missing.md", "../../outside.md"])
def test_invalid_links_fail_before_output(tmp_path: Path, target: str) -> None:
    root = _project(tmp_path)
    (root / "docs" / "README.md").write_text(f"# Docs\n\n[broken]({target})\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid local link"):
        wiki.render_pages(root)


def test_missing_home_and_casefold_collisions_fail(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "docs" / "README.md").unlink()
    with pytest.raises(ValueError, match="home page"):
        wiki.discover_pages(root)
    (root / "docs" / "README.md").write_text("# Home\n", encoding="utf-8")
    (root / "docs" / "Architecture.md").write_text("# Duplicate\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate wiki page"):
        wiki.discover_pages(root)


def test_rendered_output_checks_changes_and_preserves_unmanaged_pages(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    output = tmp_path / "wiki"
    pages = wiki.render_pages(root)
    wiki.write_pages(output, pages, root)
    custom = output / "Custom.md"
    custom.write_text("# Personal notes\n", encoding="utf-8")
    wiki.write_pages(output, pages, root)

    assert wiki.check_output(output, pages) == []
    assert custom.read_text(encoding="utf-8") == "# Personal notes\n"
    (output / "Home.md").write_text("# Changed\n", encoding="utf-8")
    assert wiki.check_output(output, pages) == ["Outdated page: Home.md"]
    with pytest.raises(ValueError, match="Hand-written page"):
        wiki.write_pages(output, pages, root)
    wiki.write_pages(output, pages, root, overwrite=True)
    assert wiki.check_output(output, pages) == []


def test_output_collision_is_checked_before_any_page_is_written(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    output = tmp_path / "wiki"
    output.mkdir()
    (output / "_Footer.md").write_text("# Keep\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Hand-written page"):
        wiki.write_pages(output, wiki.render_pages(root), root)
    assert not (output / "Home.md").exists()


def test_stale_generated_pages_require_explicit_review(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    output = tmp_path / "wiki"
    pages = wiki.render_pages(root)
    wiki.write_pages(output, pages, root)
    (output / "Old.md").write_text(wiki.GENERATED_MARKER + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Stale generated page"):
        wiki.write_pages(output, pages, root, overwrite=True)
    assert (output / "Old.md").exists()


@pytest.mark.parametrize("relative", [".", "docs", "backend/wiki", "frontend/wiki", ".git/wiki"])
def test_output_does_not_overwrite_sources(tmp_path: Path, relative: str) -> None:
    root = _project(tmp_path)
    with pytest.raises(ValueError, match="source directories"):
        wiki.write_pages(root / relative, wiki.render_pages(root), root, overwrite=True)


def test_output_symlink_is_not_followed(tmp_path: Path) -> None:
    root = _project(tmp_path / "project")
    output = tmp_path / "wiki"
    output.mkdir()
    target = tmp_path / "keep.md"
    target.write_text("# Keep\n", encoding="utf-8")
    (output / "Home.md").symlink_to(target)
    with pytest.raises(ValueError, match="Unsafe output page"):
        wiki.write_pages(output, wiki.render_pages(root), root, overwrite=True)
    assert target.read_text(encoding="utf-8") == "# Keep\n"


def test_reserved_page_names_fail(tmp_path: Path) -> None:
    root = _project(tmp_path)
    (root / "docs" / "_Footer.md").write_text("# Reserved\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate wiki page"):
        wiki.discover_pages(root)


def test_cli_checks_sources_and_generated_output_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _project(tmp_path / "project")
    monkeypatch.setattr(wiki, "PROJECT_ROOT", root)
    assert wiki.main(["--check"]) == 0
    assert not (root / "var").exists()
    output = tmp_path / "wiki"
    assert wiki.main(["--output", str(output), "--ref", "deadbeef"]) == 0
    assert wiki.main(["--check", "--output", str(output), "--ref", "deadbeef"]) == 0
    (output / "Home.md").write_text("# Edited\n", encoding="utf-8")
    assert wiki.main(["--check", "--output", str(output), "--ref", "deadbeef"]) == 1
    assert "Outdated page: Home.md" in capsys.readouterr().err
    assert wiki.main(["--check", "--ref", ""]) == 1
