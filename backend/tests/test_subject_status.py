from __future__ import annotations

from typing import Any, cast

import pytest
from examtwin.config import Settings
from examtwin.persistence.dashboard_repository import DashboardRepository
from examtwin.services import subject_status


class _MissingVectorIndex:
    def __init__(self, **_kwargs: Any) -> None:
        pass

    def get_collection(self, _name: str) -> None:
        raise RuntimeError("qdrant unavailable")


class _UnavailableDashboard:
    def stats(self, *, subject_code: str) -> dict[str, object]:
        raise RuntimeError(f"postgres unavailable for {subject_code}")


class _WorkspaceRepository:
    def __init__(self, _sessions: object) -> None:
        pass

    def resolve_subject(self, _selector: str) -> dict[str, object]:
        return {
            "knowledge_bases": [
                {
                    "id": "core",
                    "name": "Core Knowledge Base",
                    "kind": "core",
                    "active_version_id": "version-1",
                    "active_version": {
                        "version_number": 3,
                        "status": "published",
                        "vector_points": 5101,
                    },
                }
            ]
        }


def test_subject_status_catalog_survives_unavailable_runtime_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subject_status, "QdrantClient", _MissingVectorIndex)
    monkeypatch.setattr(subject_status, "WorkspaceRepository", _WorkspaceRepository)

    dashboard = cast(DashboardRepository, _UnavailableDashboard())
    result = subject_status.subject_statuses(Settings(), dashboard)

    assert {item["subject_code"] for item in result} >= {"9660", "9640"}
    assert all(item["stats"] is None for item in result)
    assert all(item["vector_index_ready"] is False for item in result)
    assert all(
        cast(list[dict[str, object]], item["knowledge_bases"])[0]["vector_points"] == 5101
        for item in result
    )
