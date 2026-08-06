from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

from llama_index.core.vector_stores import (
    FilterCondition,
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
)
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient, models

HYBRID_INDEX_SCHEMA_VERSION = "lexical-hybrid-v1"
DENSE_VECTOR_NAME = "text-dense"
SPARSE_VECTOR_NAME = "lexical-sparse-v1"
FILTER_PAYLOAD_FIELDS = (
    "subject_code",
    "unit_code",
    "pair_key",
    "source_type",
    "authority_tier",
    "source_role",
    "index_build_id",
    "index_schema_version",
    "embedding_identity",
    "node_fingerprint",
)
_LEXICAL_TOKEN_RE = re.compile(
    r"[a-zA-Z]+(?:'[a-zA-Z]+)?|\\[a-zA-Z]+|[a-zA-Z]\d+|\d+(?:\.\d+)?|[\u4e00-\u9fff]+"
)
_MAX_SPARSE_FEATURES = 4096


def _lexical_features(text: str) -> list[str]:
    tokens = [token.lower().lstrip("\\") for token in _LEXICAL_TOKEN_RE.findall(text)]
    features = [f"u:{token}" for token in tokens]
    features.extend(f"b:{left}\x1f{right}" for left, right in zip(tokens, tokens[1:], strict=False))
    return features


def _feature_index(feature: str) -> int:
    digest = hashlib.blake2s(feature.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big") & 0x7FFFFFFF


def lexical_sparse_encoder(texts: list[str]) -> tuple[list[list[int]], list[list[float]]]:
    """Encode exact terms and adjacent phrases for Qdrant's server-side IDF modifier."""

    all_indices: list[list[int]] = []
    all_values: list[list[float]] = []
    for text in texts:
        counts = Counter(_feature_index(feature) for feature in _lexical_features(text))
        if len(counts) > _MAX_SPARSE_FEATURES:
            counts = Counter(dict(counts.most_common(_MAX_SPARSE_FEATURES)))
        normalizer = math.sqrt(max(1, sum(counts.values())))
        weighted = sorted(
            (index, (1.0 + math.log(frequency)) / normalizer) for index, frequency in counts.items()
        )
        all_indices.append([index for index, _ in weighted])
        all_values.append([value for _, value in weighted])
    return all_indices, all_values


def retrieval_filters(
    *,
    subject_code: str,
    unit_code: str | None = None,
    pair_key: str | None = None,
    source_types: Sequence[str] = (),
    authority_tiers: Sequence[str] = (),
    source_roles: Sequence[str] = (),
) -> MetadataFilters:
    filters: list[MetadataFilter | MetadataFilters] = [
        MetadataFilter(key="subject_code", value=subject_code)
    ]
    if unit_code:
        filters.append(
            MetadataFilters(
                filters=[
                    MetadataFilter(key="unit_code", value=unit_code),
                    MetadataFilter(key="unit_code", value=""),
                ],
                condition=FilterCondition.OR,
            )
        )
    if pair_key:
        filters.append(MetadataFilter(key="pair_key", value=pair_key))
    if source_types:
        filters.append(
            MetadataFilter(
                key="source_type",
                value=list(dict.fromkeys(source_types)),
                operator=FilterOperator.IN,
            )
        )
    if authority_tiers:
        filters.append(
            MetadataFilter(
                key="authority_tier",
                value=list(dict.fromkeys(authority_tiers)),
                operator=FilterOperator.IN,
            )
        )
    if source_roles:
        filters.append(
            MetadataFilter(
                key="source_role",
                value=list(dict.fromkeys(source_roles)),
                operator=FilterOperator.IN,
            )
        )
    return MetadataFilters(filters=filters)


def collection_supports_hybrid(client: QdrantClient, collection_name: str) -> bool:
    info = client.get_collection(collection_name)
    sparse = info.config.params.sparse_vectors or {}
    return isinstance(sparse, dict) and SPARSE_VECTOR_NAME in sparse


def qdrant_vector_store(
    client: QdrantClient,
    collection_name: str,
    *,
    hybrid: bool,
) -> QdrantVectorStore:
    kwargs: dict[str, Any] = {
        "client": client,
        "collection_name": collection_name,
        "dense_vector_name": DENSE_VECTOR_NAME,
    }
    if hybrid:
        kwargs.update(
            {
                "enable_hybrid": True,
                "sparse_vector_name": SPARSE_VECTOR_NAME,
                "sparse_doc_fn": lexical_sparse_encoder,
                "sparse_query_fn": lexical_sparse_encoder,
                "sparse_config": models.SparseVectorParams(
                    index=models.SparseIndexParams(on_disk=False),
                    modifier=models.Modifier.IDF,
                ),
                "payload_indexes": [
                    {
                        "field_name": field,
                        "field_schema": models.PayloadSchemaType.KEYWORD,
                    }
                    for field in FILTER_PAYLOAD_FIELDS
                ],
            }
        )
    return QdrantVectorStore(**kwargs)
