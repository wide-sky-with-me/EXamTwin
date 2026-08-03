from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from qdrant_client import models


@dataclass(frozen=True)
class PublicationGate:
    expected_points: int
    indexed_points: int

    @property
    def passed(self) -> bool:
        return self.expected_points > 0 and self.indexed_points == self.expected_points


class QdrantIndexPublisher:
    """Publish immutable Qdrant builds through one stable alias."""

    def __init__(self, client: Any, *, base_collection: str, alias_name: str) -> None:
        if base_collection == alias_name:
            raise ValueError("Qdrant collection base and live alias must be different")
        self.client = client
        self.base_collection = base_collection
        self.alias_name = alias_name

    def staging_name(self, build_id: str) -> str:
        suffix = re.sub(r"[^a-zA-Z0-9]", "", build_id)[:16]
        if not suffix:
            raise ValueError("Vector index build id cannot be empty")
        return f"{self.base_collection}__staging_{suffix}"

    def alias_target(self) -> str | None:
        aliases = self.client.get_aliases().aliases
        for alias in aliases:
            if alias.alias_name == self.alias_name:
                return str(alias.collection_name)
        return None

    def bootstrap_alias(self) -> str:
        current = self.alias_target()
        if current is not None:
            return current
        if not self.client.collection_exists(self.base_collection):
            raise FileNotFoundError(
                f"Cannot bootstrap {self.alias_name}: {self.base_collection} does not exist"
            )
        self.client.update_collection_aliases(
            change_aliases_operations=[
                models.CreateAliasOperation(
                    create_alias=models.CreateAlias(
                        collection_name=self.base_collection,
                        alias_name=self.alias_name,
                    )
                )
            ]
        )
        return self.base_collection

    def validate(self, collection_name: str, expected_points: int) -> PublicationGate:
        if not self.client.collection_exists(collection_name):
            raise FileNotFoundError(f"Qdrant staging collection does not exist: {collection_name}")
        indexed_points = int(self.client.get_collection(collection_name).points_count or 0)
        gate = PublicationGate(
            expected_points=expected_points,
            indexed_points=indexed_points,
        )
        if not gate.passed:
            raise ValueError(
                "Qdrant publication gate failed: "
                f"expected {expected_points} points, found {indexed_points}"
            )
        return gate

    def publish(self, collection_name: str, expected_points: int) -> PublicationGate:
        gate = self.validate(collection_name, expected_points)
        previous = self.alias_target()
        operations: list[Any] = []
        if previous is not None:
            operations.append(
                models.DeleteAliasOperation(
                    delete_alias=models.DeleteAlias(alias_name=self.alias_name)
                )
            )
        operations.append(
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    collection_name=collection_name,
                    alias_name=self.alias_name,
                )
            )
        )
        self.client.update_collection_aliases(change_aliases_operations=operations)
        if self.alias_target() != collection_name:
            raise RuntimeError("Qdrant alias switch did not become visible")
        return gate
