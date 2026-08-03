from __future__ import annotations

from types import SimpleNamespace

import pytest
from examtwin.config import Settings
from examtwin.services.ingestion import build_vector_index
from examtwin.services.subject_context import subject_context
from examtwin.services.vector_index_publication import QdrantIndexPublisher


class FakeQdrantClient:
    def __init__(self) -> None:
        self.collections = {"examtwin_9660": 12, "staging": 15, "short": 14}
        self.aliases: dict[str, str] = {}
        self.alias_updates: list[list[object]] = []

    def collection_exists(self, name: str) -> bool:
        return name in self.collections or name in self.aliases

    def get_collection(self, name: str) -> SimpleNamespace:
        target = self.aliases.get(name, name)
        return SimpleNamespace(points_count=self.collections[target])

    def get_aliases(self) -> SimpleNamespace:
        return SimpleNamespace(
            aliases=[
                SimpleNamespace(alias_name=alias, collection_name=target)
                for alias, target in self.aliases.items()
            ]
        )

    def update_collection_aliases(self, *, change_aliases_operations: list[object]) -> None:
        self.alias_updates.append(change_aliases_operations)
        updated = dict(self.aliases)
        for operation in change_aliases_operations:
            if getattr(operation, "delete_alias", None) is not None:
                updated.pop(operation.delete_alias.alias_name, None)
            if getattr(operation, "create_alias", None) is not None:
                updated[operation.create_alias.alias_name] = operation.create_alias.collection_name
        self.aliases = updated


def test_bootstrap_and_publish_switch_alias_atomically() -> None:
    client = FakeQdrantClient()
    publisher = QdrantIndexPublisher(
        client,
        base_collection="examtwin_9660",
        alias_name="examtwin_9660_live",
    )

    assert publisher.bootstrap_alias() == "examtwin_9660"
    gate = publisher.publish("staging", expected_points=15)

    assert gate.passed
    assert publisher.alias_target() == "staging"
    assert len(client.alias_updates[-1]) == 2


def test_publication_gate_keeps_live_alias_on_incomplete_staging() -> None:
    client = FakeQdrantClient()
    client.aliases["examtwin_9660_live"] = "examtwin_9660"
    publisher = QdrantIndexPublisher(
        client,
        base_collection="examtwin_9660",
        alias_name="examtwin_9660_live",
    )

    with pytest.raises(ValueError, match="expected 15 points, found 14"):
        publisher.publish("short", expected_points=15)

    assert publisher.alias_target() == "examtwin_9660"
    assert client.alias_updates == []


def test_collection_base_and_alias_cannot_collide() -> None:
    with pytest.raises(ValueError, match="must be different"):
        QdrantIndexPublisher(
            FakeQdrantClient(),
            base_collection="same",
            alias_name="same",
        )


def test_partial_index_cannot_replace_live_alias() -> None:
    with pytest.raises(ValueError, match="Partial vector indexes cannot be published"):
        settings = Settings()
        build_vector_index(
            settings,
            subject_context(settings),
            None,  # type: ignore[arg-type]
            None,  # type: ignore[arg-type]
            limit=1,
        )
