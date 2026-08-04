from pathlib import Path
from typing import Any

import pytest
from examtwin.answering_agent.contracts import AgentRunContext, AnswerTask
from examtwin.answering_agent.tools.source_read import SourceReadTool
from examtwin.config import Settings
from examtwin.schemas import Citation
from examtwin.services.source_context import source_context


class FakeDocumentReader:
    def __init__(self, markdown_path: str | Path):
        self.markdown_path = markdown_path

    def get_converted(self, _document_id: str) -> dict[str, Any]:
        return {
            "id": "doc-1",
            "path": "licensed/textbook.pdf",
            "markdown_path": str(self.markdown_path),
        }


def _legacy_cache(tmp_path: Path) -> tuple[FakeDocumentReader, Settings]:
    cache_root = tmp_path / "corpus" / "md"
    cache_root.mkdir(parents=True)
    (cache_root / "doc-1.md").write_text(
        "# Legacy source\n\nThe complete cached explanation.",
        encoding="utf-8",
    )
    documents = FakeDocumentReader("/home/previous-user/workspace/EXamTwin/var/corpus/md/doc-1.md")
    return documents, Settings(object_store_local_root=tmp_path)


def test_source_context_returns_complete_page_for_both_page_marker_styles(
    tmp_path: Path,
) -> None:
    markdown_path = tmp_path / "corpus" / "md" / "textbook.md"
    markdown_path.parent.mkdir(parents=True)
    markdown_path.write_text(
        "<!-- page:21 -->\n# Previous\nold\n\n"
        "<!-- page 22 -->\n# Integration by parts\n"
        "The complete derivation and worked example.\n\n"
        "<!-- page:23 -->\n# Next\nnew\n",
        encoding="utf-8",
    )

    result = source_context(
        FakeDocumentReader(markdown_path),
        Settings(object_store_local_root=tmp_path),
        "doc-1",
        page=22,
        query="integration by parts",
    )

    assert "# Integration by parts" in result.content_markdown
    assert "complete derivation" in result.content_markdown
    assert "# Next" not in result.content_markdown
    assert result.truncated is False


def test_source_context_keeps_a_large_mineru_table_whole(tmp_path: Path) -> None:
    markdown_path = tmp_path / "corpus" / "md" / "table.md"
    markdown_path.parent.mkdir(parents=True)
    table = "<table>" + ("<tr><td>whole row</td></tr>" * 2500) + "</table>"
    markdown_path.write_text(f"# Mark scheme\n\n{table}\n", encoding="utf-8")

    result = source_context(
        FakeDocumentReader(markdown_path),
        Settings(object_store_local_root=tmp_path),
        "doc-1",
        query="mark scheme",
    )

    assert result.truncated is False
    assert result.content_markdown.endswith("</table>")
    assert result.content_markdown.count("<tr>") == 2500


def test_source_context_maps_legacy_host_absolute_path_to_current_cache(
    tmp_path: Path,
) -> None:
    documents, settings = _legacy_cache(tmp_path)

    result = source_context(
        documents,
        settings,
        "doc-1",
        query="cached explanation",
    )

    assert "The complete cached explanation." in result.content_markdown


def test_source_context_prefers_s3_after_legacy_cache_migration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    documents, _settings = _legacy_cache(tmp_path)
    canonical = tmp_path / "object-cache" / "corpus" / "md" / "doc-1.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("# Canonical S3 source\n\nRead from object storage.", encoding="utf-8")
    requested: list[str] = []

    class FakeS3Backend:
        def materialize(self, key: str) -> Path:
            requested.append(key)
            if key == "corpus/md/doc-1.md":
                return canonical
            raise LookupError("missing")

    monkeypatch.setattr(
        "examtwin.services.cache_paths.build_storage_backend",
        lambda _settings: FakeS3Backend(),
    )
    settings = Settings(
        object_store_backend="s3",
        object_store_local_root=tmp_path,
        object_store_cache_dir=tmp_path / "object-cache",
    )

    result = source_context(documents, settings, "doc-1", query="object storage")

    assert "Read from object storage." in result.content_markdown
    assert "Legacy source" not in result.content_markdown
    assert requested == ["corpus/md/doc-1.md"]


def test_source_context_rejects_existing_markdown_outside_cache_root(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "corpus" / "md"
    cache_root.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("# Must not be readable", encoding="utf-8")

    with pytest.raises(LookupError, match="原文缓存不存在"):
        source_context(
            FakeDocumentReader(outside),
            Settings(object_store_local_root=tmp_path),
            "doc-1",
        )


def test_source_context_rejects_cache_symlink_that_escapes_root(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "corpus" / "md"
    cache_root.mkdir(parents=True)
    outside = tmp_path / "outside.md"
    outside.write_text("# Must not be readable", encoding="utf-8")
    cache_link = cache_root / "doc-1.md"
    cache_link.symlink_to(outside)

    with pytest.raises(LookupError, match="原文缓存不存在"):
        source_context(
            FakeDocumentReader(cache_link),
            Settings(object_store_local_root=tmp_path),
            "doc-1",
        )


@pytest.mark.asyncio
async def test_answering_source_read_uses_legacy_cache_resolution(
    tmp_path: Path,
) -> None:
    documents, settings = _legacy_cache(tmp_path)
    context = AgentRunContext(task=AnswerTask(subject_code="9660", question="Explain the source."))
    context.add_citation(
        Citation(
            source="licensed/textbook.pdf",
            document_id="doc-1",
            excerpt="Cached evidence.",
        )
    )
    tool = SourceReadTool(
        documents,
        settings,
    ).bind(context)

    result = await tool.acall(document_id="doc-1", query="cached explanation")

    assert "The complete cached explanation." in result.content
