from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from examtwin.platform.database.models import (
    GraphEdgeModel,
    GraphNodeModel,
    GraphVersionModel,
    SubjectModel,
)
from examtwin.platform.database.session import utcnow


def _version_dict(row: GraphVersionModel) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _node_dict(row: GraphNodeModel) -> dict[str, Any]:
    result = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    result["aliases"] = json.loads(row.aliases_json)
    result["evidence"] = json.loads(row.evidence_json)
    result["metadata"] = json.loads(row.metadata_json)
    return result


def _edge_dict(row: GraphEdgeModel) -> dict[str, Any]:
    result = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    result["evidence"] = json.loads(row.evidence_json)
    return result


class GraphRepository:
    """Own graph draft review, version publication, and active-version selection."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def create_version(
        self,
        *,
        subject_id: str,
        knowledge_base_version_id: str,
        source_hash: str,
        model_name: str,
        prompt_version: str,
    ) -> str:
        now = utcnow()
        version_id = str(uuid.uuid4())
        with self.sessions.begin() as session:
            number = (
                int(
                    session.scalar(
                        select(func.coalesce(func.max(GraphVersionModel.version_number), 0)).where(
                            GraphVersionModel.subject_id == subject_id
                        )
                    )
                    or 0
                )
                + 1
            )
            session.add(
                GraphVersionModel(
                    id=version_id,
                    subject_id=subject_id,
                    knowledge_base_version_id=knowledge_base_version_id,
                    version_number=number,
                    status="building",
                    source_hash=source_hash,
                    model_name=model_name,
                    prompt_version=prompt_version,
                    created_at=now,
                    updated_at=now,
                    published_at=None,
                )
            )
        return version_id

    def store_draft(
        self,
        version_id: str,
        *,
        nodes: Sequence[Mapping[str, Any]],
        edges: Sequence[Mapping[str, Any]],
    ) -> None:
        now = utcnow()
        with self.sessions.begin() as session:
            version = session.get(GraphVersionModel, version_id)
            if version is None:
                raise LookupError("知识图谱版本不存在")
            session.add_all(
                GraphNodeModel(
                    id=str(uuid.uuid4()),
                    graph_version_id=version_id,
                    created_at=now,
                    updated_at=now,
                    **dict(item),
                )
                for item in nodes
            )
            session.add_all(
                GraphEdgeModel(
                    id=str(uuid.uuid4()),
                    graph_version_id=version_id,
                    created_at=now,
                    updated_at=now,
                    **dict(item),
                )
                for item in edges
            )
            version.status = "draft"
            version.updated_at = now

    def fail_version(self, version_id: str) -> None:
        with self.sessions.begin() as session:
            version = session.get(GraphVersionModel, version_id)
            if version is not None:
                version.status = "failed"
                version.updated_at = utcnow()

    def list_versions(self, subject_id: str) -> list[dict[str, Any]]:
        statement = (
            select(GraphVersionModel)
            .where(GraphVersionModel.subject_id == subject_id)
            .order_by(GraphVersionModel.version_number.desc())
        )
        with self.sessions() as session:
            return [_version_dict(row) for row in session.scalars(statement)]

    def get(self, version_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            version = session.get(GraphVersionModel, version_id)
            if version is None:
                raise LookupError("知识图谱版本不存在")
            nodes = list(
                session.scalars(
                    select(GraphNodeModel)
                    .where(GraphNodeModel.graph_version_id == version_id)
                    .order_by(GraphNodeModel.code, GraphNodeModel.title)
                )
            )
            edges = list(
                session.scalars(
                    select(GraphEdgeModel)
                    .where(GraphEdgeModel.graph_version_id == version_id)
                    .order_by(
                        GraphEdgeModel.source_key,
                        GraphEdgeModel.target_key,
                        GraphEdgeModel.relation_type,
                    )
                )
            )
        result = _version_dict(version)
        result["nodes"] = [_node_dict(row) for row in nodes]
        result["edges"] = [_edge_dict(row) for row in edges]
        return result

    def delete(self, version_id: str, *, subject_id: str) -> None:
        with self.sessions.begin() as session:
            version = session.scalar(
                select(GraphVersionModel)
                .where(
                    GraphVersionModel.id == version_id,
                    GraphVersionModel.subject_id == subject_id,
                )
                .with_for_update()
            )
            if version is None:
                raise LookupError("知识图谱版本不存在")
            subject = session.get(SubjectModel, subject_id)
            if subject is None:
                raise LookupError("科目工作区不存在")
            if subject.active_graph_version_id == version_id:
                subject.active_graph_version_id = None
                subject.updated_at = utcnow()
            session.delete(version)

    def review_node(
        self,
        version_id: str,
        node_id: str,
        values: Mapping[str, Any],
    ) -> dict[str, Any]:
        allowed = {
            "title",
            "description",
            "node_type",
            "aliases_json",
            "parent_key",
            "review_status",
        }
        updates = {key: value for key, value in values.items() if key in allowed}
        with self.sessions.begin() as session:
            node = session.get(GraphNodeModel, node_id)
            if node is None or node.graph_version_id != version_id:
                raise LookupError("知识图谱节点不存在")
            for key, value in updates.items():
                setattr(node, key, value)
            node.updated_at = utcnow()
        return _node_dict(node)

    def review_edge(
        self,
        version_id: str,
        edge_id: str,
        *,
        relation_type: str | None,
        review_status: str,
    ) -> dict[str, Any]:
        with self.sessions.begin() as session:
            edge = session.get(GraphEdgeModel, edge_id)
            if edge is None or edge.graph_version_id != version_id:
                raise LookupError("知识图谱关系不存在")
            if relation_type is not None:
                edge.relation_type = relation_type
            edge.review_status = review_status
            edge.updated_at = utcnow()
        return _edge_dict(edge)

    def review_all(self, version_id: str, review_status: str) -> dict[str, Any]:
        if review_status not in {"accepted", "rejected"}:
            raise ValueError("无效的审核状态")
        now = utcnow()
        with self.sessions.begin() as session:
            version = session.get(GraphVersionModel, version_id)
            if version is None:
                raise LookupError("知识图谱版本不存在")
            session.execute(
                update(GraphNodeModel)
                .where(
                    GraphNodeModel.graph_version_id == version_id,
                    GraphNodeModel.review_status == "pending",
                )
                .values(review_status=review_status, updated_at=now)
            )
            session.execute(
                update(GraphEdgeModel)
                .where(
                    GraphEdgeModel.graph_version_id == version_id,
                    GraphEdgeModel.review_status == "pending",
                )
                .values(review_status=review_status, updated_at=now)
            )
            version.updated_at = now
        return self.get(version_id)

    def expansion_terms(
        self,
        version_id: str,
        query: str,
        *,
        limit: int = 16,
    ) -> list[str]:
        tokens = set(re.findall(r"[a-z0-9]{3,}", query.casefold()))
        if not tokens:
            return []
        with self.sessions() as session:
            nodes = list(
                session.scalars(
                    select(GraphNodeModel).where(
                        GraphNodeModel.graph_version_id == version_id,
                        GraphNodeModel.review_status == "accepted",
                    )
                )
            )
            edges = list(
                session.scalars(
                    select(GraphEdgeModel).where(
                        GraphEdgeModel.graph_version_id == version_id,
                        GraphEdgeModel.review_status == "accepted",
                    )
                )
            )
        by_key = {node.stable_key: node for node in nodes}
        ranked = sorted(
            (
                (
                    len(
                        tokens
                        & set(
                            re.findall(
                                r"[a-z0-9]{3,}",
                                (
                                    f"{node.title} {' '.join(json.loads(node.aliases_json))}"
                                ).casefold(),
                            )
                        )
                    ),
                    node,
                )
                for node in nodes
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        seed_keys = {node.stable_key for score, node in ranked[:5] if score > 0}
        related_keys = set(seed_keys)
        for edge in edges:
            if edge.source_key in seed_keys:
                related_keys.add(edge.target_key)
            if edge.target_key in seed_keys:
                related_keys.add(edge.source_key)
        terms: list[str] = []
        for key in related_keys:
            node = by_key.get(key)
            if node is None or node.node_type == "subject":
                continue
            terms.extend([node.title, *json.loads(node.aliases_json)])
            if len(terms) >= limit:
                break
        return list(dict.fromkeys(term for term in terms if term.strip()))[:limit]

    def publish(self, version_id: str) -> dict[str, Any]:

        now = utcnow()
        with self.sessions.begin() as session:
            version = session.scalar(
                select(GraphVersionModel)
                .where(GraphVersionModel.id == version_id)
                .with_for_update()
            )
            if version is None:
                raise LookupError("知识图谱版本不存在")
            if version.status != "draft":
                raise ValueError("只有草稿知识图谱可以发布")
            pending_nodes = session.scalar(
                select(func.count())
                .select_from(GraphNodeModel)
                .where(
                    GraphNodeModel.graph_version_id == version_id,
                    GraphNodeModel.review_status == "pending",
                )
            )
            pending_edges = session.scalar(
                select(func.count())
                .select_from(GraphEdgeModel)
                .where(
                    GraphEdgeModel.graph_version_id == version_id,
                    GraphEdgeModel.review_status == "pending",
                )
            )
            accepted_nodes = session.scalar(
                select(func.count())
                .select_from(GraphNodeModel)
                .where(
                    GraphNodeModel.graph_version_id == version_id,
                    GraphNodeModel.review_status == "accepted",
                )
            )
            if pending_nodes or pending_edges:
                raise ValueError("发布前必须审核所有节点和关系")
            if not accepted_nodes:
                raise ValueError("知识图谱没有已接受的节点")
            subject = session.get(SubjectModel, version.subject_id)
            if subject is None:
                raise LookupError("科目工作区不存在")
            version.status = "published"
            version.updated_at = now
            version.published_at = now
            subject.active_graph_version_id = version.id
            subject.updated_at = now
        return self.get(version_id)
