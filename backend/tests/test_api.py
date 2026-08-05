import pytest
from examtwin.contracts.system import API_CAPABILITIES, API_CONTRACT_VERSION
from examtwin.main import app


@pytest.mark.integration
def test_health_and_knowledge_graph() -> None:
    from examtwin.config import get_settings
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        health = client.get("/api/v1/health")
        assert health.status_code == 200
        assert health.json()["subject_code"] is None
        assert health.json()["api_contract_version"] == API_CONTRACT_VERSION
        assert health.json()["capabilities"] == list(API_CAPABILITIES)
        assert health.json()["infrastructure"] == {
            "postgresql": True,
            "qdrant": True,
            "object_storage": True,
        }
        assert health.json()["object_storage_backend"] == get_settings().object_store_backend

        subjects = client.get("/api/v1/subjects")
        assert subjects.status_code == 200
        assert {item["subject_code"] for item in subjects.json()} >= {"9660", "9640"}

        assert client.get("/api/v1/subject").status_code == 400
        headers = {"X-ExamTwin-Subject": "oxfordaqa-mathematics-9660"}
        subject = client.get("/api/v1/subject", headers=headers)
        assert subject.status_code == 200
        assert subject.json()["subject_code"] == "9660"
        assert {item["code"] for item in subject.json()["units"]} == {
            "P1",
            "PSM1",
            "P2",
            "S2",
            "M2",
        }

        points = client.get("/api/v1/knowledge/points", headers=headers)
        assert points.status_code == 200
        assert isinstance(points.json(), list)
