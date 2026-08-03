import pytest
from examtwin.main import app


@pytest.mark.integration
def test_health_and_knowledge_graph() -> None:
    from examtwin.config import get_settings
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["subject_code"] == "9660"
        assert health.json()["api_contract_version"] == "2026-08-03.persistence-hardening-v11"
        assert "syllabus_driven_curriculum_v1" in health.json()["capabilities"]
        assert "curriculum_candidates_v1" in health.json()["capabilities"]
        assert "structured_answer_output_v1" in health.json()["capabilities"]
        assert "paper_jobs_v1" in health.json()["capabilities"]
        assert "task_events_v1" in health.json()["capabilities"]
        assert "answering_agent_v1" in health.json()["capabilities"]
        assert "required_answer_diagrams_v1" in health.json()["capabilities"]
        assert "paper_agent_steps_v1" in health.json()["capabilities"]
        assert "paper_question_vision_v1" in health.json()["capabilities"]
        assert "selective_question_vision_v1" in health.json()["capabilities"]
        assert "paper_question_concurrency_v1" in health.json()["capabilities"]
        assert "paper_question_retry_v1" in health.json()["capabilities"]
        assert "answer_images_v1" in health.json()["capabilities"]
        assert "question_answer_contract_v1" in health.json()["capabilities"]
        assert "paired_exam_evidence_v1" in health.json()["capabilities"]
        assert "adaptive_tool_budget_v1" in health.json()["capabilities"]
        assert "probability_calculator_v1" in health.json()["capabilities"]
        assert "subject_pack_v1" in health.json()["capabilities"]
        assert "knowledge_build_runs_v1" in health.json()["capabilities"]
        assert "syllabus_ai_difficulty_v1" in health.json()["capabilities"]
        assert "vector_index_atomic_publication_v1" in health.json()["capabilities"]
        assert "versioned_schema_migrations_v1" in health.json()["capabilities"]
        assert "economics_subject_pack_9640_v1" in health.json()["capabilities"]
        assert "managed_object_storage_v1" in health.json()["capabilities"]
        assert "bounded_paper_upload_v1" in health.json()["capabilities"]
        assert "source_identity_diagnostics_v1" in health.json()["capabilities"]
        assert "local_only_access_v1" in health.json()["capabilities"]
        assert (
            health.json()["object_storage_backend"]
            == get_settings().object_store_backend
        )

        subject = client.get("/api/v1/subject")
        assert subject.status_code == 200
        assert subject.json()["subject_code"] == "9660"
        assert {item["code"] for item in subject.json()["units"]} == {
            "P1",
            "PSM1",
            "P2",
            "S2",
            "M2",
        }

        points = client.get("/api/v1/knowledge/points")
        assert points.status_code == 200
        payload = points.json()
        assert len(payload) >= 38
        assert {item["unit_code"] for item in payload} >= {"P1", "PSM1", "P2", "S2", "M2"}
