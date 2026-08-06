from __future__ import annotations

import logging

from qdrant_client import QdrantClient

from examtwin.platform.config import Settings
from examtwin.platform.database.session import create_session_factory
from examtwin.subjects.dashboard_repository import DashboardRepository
from examtwin.subjects.public import all_subject_contexts
from examtwin.subjects.workspace_repository import WorkspaceRepository

logger = logging.getLogger(__name__)


def subject_statuses(
    settings: Settings,
    dashboard: DashboardRepository,
) -> list[dict[str, object]]:
    """Build a bounded, provider-free status projection for every installed subject."""

    client = QdrantClient(url=settings.qdrant_url, timeout=3)
    workspaces = WorkspaceRepository(create_session_factory(settings.database_url))
    statuses: list[dict[str, object]] = []
    for context in all_subject_contexts(settings):
        vector_ready = bool(context.vector_collections)
        vector_points = 0
        for collection in context.vector_collections or (context.vector_alias,):
            try:
                info = client.get_collection(collection)
                vector_ready = vector_ready and str(info.status).lower().endswith("green")
                vector_points += int(info.points_count or 0)
            except Exception:
                vector_ready = False
        stats: dict[str, object] | None = None
        try:
            stats = dashboard.stats(subject_code=context.subject_code)
        except Exception:
            logger.warning(
                "subject_status_stats_unavailable subject_code=%s",
                context.subject_code,
                exc_info=True,
            )
        package = context.package
        workspace = workspaces.resolve_subject(context.id) or {"knowledge_bases": []}
        knowledge_bases = []
        for base in workspace.get("knowledge_bases", []):
            active = base.get("active_version")
            knowledge_bases.append(
                {
                    "id": base["id"],
                    "name": base["name"],
                    "kind": base["kind"],
                    "active_version_id": base.get("active_version_id"),
                    "active_version_number": active.get("version_number") if active else None,
                    "status": active.get("status") if active else "empty",
                    "vector_points": int(active.get("vector_points", 0)) if active else 0,
                }
            )
        statuses.append(
            {
                "id": context.id,
                "version": package.manifest.version,
                "digest": package.digest,
                "subject_code": context.subject_code,
                "title": context.pack.title,
                "board_name": context.board_name,
                "capability_profile_id": context.capability_profile_id,
                "generic_qa_enabled": True,
                "answering_enabled": context.paper_answering_enabled,
                "answering_disabled_reason": context.answering_disabled_reason,
                "active_graph_version_id": context.graph_version_id,
                "units": [
                    {"code": unit.code, "title": unit.title, "strand": unit.strand}
                    for unit in context.pack.unit_rules
                ],
                "knowledge_bases": knowledge_bases,
                "vector_alias": context.vector_alias,
                "vector_index_ready": vector_ready,
                "vector_points": vector_points,
                "stats": stats,
            }
        )
    return statuses
