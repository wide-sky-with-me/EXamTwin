from __future__ import annotations

import uuid

import pytest
from examtwin.contracts.graphs import GraphVersionSummary
from examtwin.knowledge.graph_repository import GraphRepository
from examtwin.platform.config import get_settings
from examtwin.platform.database.migrations import upgrade_database
from examtwin.platform.database.models import (
    GraphEdgeModel,
    GraphNodeModel,
    GraphVersionModel,
    SubjectModel,
)
from examtwin.platform.database.session import create_session_factory, utcnow
from sqlalchemy import func, select


@pytest.mark.integration
def test_delete_graph_version_preserves_other_versions_and_clears_active_pointer() -> None:
    settings = get_settings()
    upgrade_database(settings.database_url)
    sessions = create_session_factory(settings.database_url)
    token = uuid.uuid4().hex
    subject_id = f"subject-{token}"
    other_subject_id = f"other-subject-{token}"
    first_id = f"graph-first-{token}"
    active_id = f"graph-active-{token}"
    now = utcnow()

    with sessions.begin() as session:
        session.add_all(
            [
                SubjectModel(
                    id=subject_id,
                    subject_code=f"A{token[:8]}",
                    title="Graph subject",
                    board_name="Test board",
                    active_graph_version_id=active_id,
                    created_at=now,
                    updated_at=now,
                ),
                SubjectModel(
                    id=other_subject_id,
                    subject_code=f"B{token[:8]}",
                    title="Other subject",
                    board_name="Test board",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                GraphVersionModel(
                    id=first_id,
                    subject_id=subject_id,
                    knowledge_base_version_id=None,
                    version_number=1,
                    status="building",
                    source_hash=f"first-{token}",
                    model_name="test",
                    prompt_version="test",
                    created_at=now,
                    updated_at=now,
                    published_at=None,
                ),
                GraphVersionModel(
                    id=active_id,
                    subject_id=subject_id,
                    knowledge_base_version_id=None,
                    version_number=2,
                    status="published",
                    source_hash=f"active-{token}",
                    model_name="test",
                    prompt_version="test",
                    created_at=now,
                    updated_at=now,
                    published_at=now,
                ),
            ]
        )
        session.flush()
        session.add_all(
            [
                GraphNodeModel(
                    id=f"node-a-{token}",
                    graph_version_id=active_id,
                    stable_key="formula:a",
                    code="KG-1",
                    title="Formula A",
                    description="",
                    node_type="formula",
                    aliases_json="[]",
                    parent_key=None,
                    unit_code="U1",
                    evidence_json="[]",
                    confidence=1,
                    review_status="accepted",
                    metadata_json="{}",
                    created_at=now,
                    updated_at=now,
                ),
                GraphNodeModel(
                    id=f"node-b-{token}",
                    graph_version_id=active_id,
                    stable_key="concept:b",
                    code="KG-2",
                    title="Concept B",
                    description="",
                    node_type="concept",
                    aliases_json="[]",
                    parent_key=None,
                    unit_code="U1",
                    evidence_json="[]",
                    confidence=1,
                    review_status="accepted",
                    metadata_json="{}",
                    created_at=now,
                    updated_at=now,
                ),
                GraphEdgeModel(
                    id=f"edge-{token}",
                    graph_version_id=active_id,
                    source_key="formula:a",
                    target_key="concept:b",
                    relation_type="applies_to",
                    evidence_json="[]",
                    confidence=1,
                    review_status="accepted",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )

    repository = GraphRepository(sessions)
    with pytest.raises(LookupError):
        repository.delete(first_id, subject_id=other_subject_id)

    repository.delete(active_id, subject_id=subject_id)

    remaining = repository.list_versions(subject_id)
    assert [row["id"] for row in remaining] == [first_id]
    assert GraphVersionSummary.model_validate(remaining[0]).status == "building"
    with sessions() as session:
        subject = session.get(SubjectModel, subject_id)
        assert subject is not None
        assert subject.active_graph_version_id is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(GraphNodeModel)
                .where(GraphNodeModel.graph_version_id == active_id)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(GraphEdgeModel)
                .where(GraphEdgeModel.graph_version_id == active_id)
            )
            == 0
        )
