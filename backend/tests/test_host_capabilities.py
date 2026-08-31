from __future__ import annotations

from typing import Any

import pytest
from examtwin.assessment.answering_agent.host_capabilities import build_host_answering_tools
from examtwin.contracts.evidence import Citation
from examtwin.platform.config import Settings
from llama_index.core.schema import NodeWithScore


def _retriever(*_args: Any, **_kwargs: Any) -> list[NodeWithScore]:
    return []


def _citation_factory(_node: NodeWithScore) -> Citation:
    raise AssertionError("citation construction is not needed while assembling capabilities")


def _build(
    *names: str,
    required_names: tuple[str, ...] = (),
    known_external_names: frozenset[str] = frozenset(),
):
    return build_host_answering_tools(
        Settings(),
        allowed_names=names,
        required_names=required_names,
        known_external_names=known_external_names,
        retriever=_retriever,
        citation_factory=_citation_factory,
        question_vision_provider=None,
        vision_llm=None,
        image_generation_provider=None,
        documents=None,
        object_store=None,
    )


def test_host_catalog_builds_only_requested_registered_capabilities() -> None:
    tools = _build("knowledge_search", "math_calculate")

    assert tuple(tool.name for tool in tools) == ("knowledge_search", "math_calculate")


def test_host_catalog_distinguishes_unknown_and_known_unavailable_capabilities() -> None:
    with pytest.raises(ValueError, match="unknown answering capabilities: typo_tool"):
        _build("typo_tool")

    assert _build("image_generate") == ()
    with pytest.raises(ValueError, match="known but unavailable: image_generate"):
        _build("image_generate", required_names=("image_generate",))


def test_host_catalog_leaves_declared_external_capabilities_to_external_provider() -> None:
    assert (
        _build(
            "reviewed_external_tool",
            known_external_names=frozenset({"reviewed_external_tool"}),
        )
        == ()
    )
