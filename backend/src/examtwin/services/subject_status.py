from __future__ import annotations

import logging

from examtwin.config import Settings
from examtwin.persistence.dashboard_repository import DashboardRepository
from examtwin.services.subject_context import all_subject_contexts
from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)


def subject_statuses(
    settings: Settings,
    dashboard: DashboardRepository,
) -> list[dict[str, object]]:
    """Build a bounded, provider-free status projection for every installed subject."""

    client = QdrantClient(url=settings.qdrant_url, timeout=3)
    statuses: list[dict[str, object]] = []
    for context in all_subject_contexts(settings):
        vector_ready = False
        vector_points = 0
        try:
            info = client.get_collection(context.vector_alias)
            vector_ready = str(info.status).lower().endswith("green")
            vector_points = int(info.points_count or 0)
        except Exception:
            # The platform status endpoint must still show corpus/graph state when Qdrant
            # is degraded or this subject has not published an index yet.
            pass
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
        statuses.append(
            {
                "id": context.pack.id,
                "version": package.manifest.version,
                "digest": package.digest,
                "subject_code": context.subject_code,
                "title": context.pack.title,
                "board_name": context.pack.board.name,
                "answering_enabled": package.answering_enabled,
                "answering_disabled_reason": package.answering_disabled_reason,
                "units": [
                    {"code": unit.code, "title": unit.title, "strand": unit.strand}
                    for unit in context.pack.unit_rules
                ],
                "vector_alias": context.vector_alias,
                "vector_index_ready": vector_ready,
                "vector_points": vector_points,
                "stats": stats,
            }
        )
    return statuses
