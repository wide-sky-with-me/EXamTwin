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


def test_subject_status_catalog_survives_unavailable_runtime_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subject_status, "QdrantClient", _MissingVectorIndex)

    dashboard = cast(DashboardRepository, _UnavailableDashboard())
    result = subject_status.subject_statuses(Settings(), dashboard)

    assert {item["subject_code"] for item in result} >= {"9660", "9640"}
    assert all(item["stats"] is None for item in result)
    assert all(item["vector_index_ready"] is False for item in result)
