from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from dataclasses import dataclass
from typing import Any

from llama_index.core.schema import BaseNode, MetadataMode
from qdrant_client import QdrantClient

from examtwin.knowledge.vector_retrieval import DENSE_VECTOR_NAME

_BATCH_SIZE = 128
_VOLATILE_EMBED_METADATA = (
    "document_id",
    "source",
    "filename",
    "pair_key",
    "index_build_id",
    "index_schema_version",
    "embedding_identity",
    "node_fingerprint",
    "knowledge_match_confidence",
)


@dataclass(frozen=True)
class VectorWritePlan:
    pending_nodes: list[BaseNode]
    resumed_points: int
    reused_embeddings: int

    @property
    def embeddings_required(self) -> int:
        return sum(node.embedding is None for node in self.pending_nodes)


def embedding_identity(*, base_url: str, model: str) -> str:
    """Identify embedding semantics without persisting a credential."""

    material = json.dumps(
        {"base_url": base_url.rstrip("/"), "model": model},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _batches(values: list[str]) -> list[list[str]]:
    return [values[offset : offset + _BATCH_SIZE] for offset in range(0, len(values), _BATCH_SIZE)]


def _existing_ids(
    client: QdrantClient,
    collection_name: str | None,
    node_ids: list[str],
) -> set[str]:
    if not collection_name or not client.collection_exists(collection_name):
        return set()
    found: set[str] = set()
    for batch in _batches(node_ids):
        found.update(
            str(record.id)
            for record in client.retrieve(
                collection_name,
                ids=batch,
                with_payload=False,
                with_vectors=False,
            )
        )
    return found


def _prepare_node_identities(
    nodes: list[BaseNode],
    *,
    build_id: str,
    schema_version: str,
    embed_identity: str,
) -> None:
    occurrences: Counter[str] = Counter()
    for node in nodes:
        node.excluded_embed_metadata_keys = list(
            dict.fromkeys([*node.excluded_embed_metadata_keys, *_VOLATILE_EMBED_METADATA])
        )
        embedding_content = node.get_content(metadata_mode=MetadataMode.EMBED)
        embedding_fingerprint = hashlib.sha256(embedding_content.encode("utf-8")).hexdigest()
        identity_material = json.dumps(
            {
                "embedding_fingerprint": embedding_fingerprint,
                "node_kind": node.metadata.get("node_kind"),
                "document_id": node.metadata.get("document_id"),
                "page": node.metadata.get("page"),
                "section": node.metadata.get("section"),
                "block_kind": node.metadata.get("block_kind"),
                "table_index": node.metadata.get("table_index"),
                "knowledge_code": node.metadata.get("knowledge_code"),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        occurrence = occurrences[identity_material]
        occurrences[identity_material] += 1
        fingerprint = hashlib.sha256(f"{identity_material}:{occurrence}".encode()).hexdigest()

        # Tables and knowledge points already have stable domain-owned UUIDs. Prose
        # chunks historically inherited random SentenceSplitter UUIDs, so only those
        # need replacement with a content identity.
        if (
            node.metadata.get("block_kind") != "table"
            and node.metadata.get("node_kind") != "knowledge_point"
        ):
            node.id_ = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"https://examtwin.local/evidence/prose/{fingerprint}",
                )
            )
        node.metadata.update(
            {
                "index_build_id": build_id,
                "index_schema_version": schema_version,
                "embedding_identity": embed_identity,
                "node_fingerprint": fingerprint,
            }
        )


def _dense_vector(record: Any) -> list[float] | None:
    vectors = record.vector
    if not isinstance(vectors, dict):
        return None
    dense = vectors.get(DENSE_VECTOR_NAME)
    if not isinstance(dense, list):
        return None
    return [float(value) for value in dense]


def plan_vector_writes(
    client: QdrantClient,
    nodes: list[BaseNode],
    *,
    staging_collection: str,
    previous_collection: str | None,
    build_id: str,
    schema_version: str,
    embed_identity: str,
) -> VectorWritePlan:
    """Skip resumed points and hydrate unchanged nodes from the previous live index."""

    _prepare_node_identities(
        nodes,
        build_id=build_id,
        schema_version=schema_version,
        embed_identity=embed_identity,
    )
    node_by_id = {node.node_id: node for node in nodes}
    if len(node_by_id) != len(nodes):
        raise ValueError("Vector node identity collision detected")

    resumed_ids = _existing_ids(client, staging_collection, list(node_by_id))
    pending_nodes = [node for node in nodes if node.node_id not in resumed_ids]
    if not previous_collection or not client.collection_exists(previous_collection):
        return VectorWritePlan(pending_nodes, len(resumed_ids), 0)

    reused = 0
    pending_by_id = {node.node_id: node for node in pending_nodes}
    for batch in _batches(list(pending_by_id)):
        records = client.retrieve(
            previous_collection,
            ids=batch,
            with_payload=True,
            with_vectors=[DENSE_VECTOR_NAME],
        )
        for record in records:
            node = pending_by_id.get(str(record.id))
            payload = record.payload or {}
            if node is None:
                continue
            if payload.get("index_schema_version") != schema_version:
                continue
            if payload.get("embedding_identity") != embed_identity:
                continue
            if payload.get("node_fingerprint") != node.metadata["node_fingerprint"]:
                continue
            dense = _dense_vector(record)
            if dense is None:
                continue
            node.embedding = dense
            reused += 1

    return VectorWritePlan(pending_nodes, len(resumed_ids), reused)
