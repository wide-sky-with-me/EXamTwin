from examtwin.api import system
from examtwin.config import Settings
from examtwin.contracts.system import API_CAPABILITIES, API_CONTRACT_VERSION
from examtwin.healthcheck import health_payload_is_valid
from examtwin.services import health as health_service


def test_infrastructure_health_keeps_component_failures_independent(monkeypatch) -> None:
    settings = Settings()
    monkeypatch.setattr(health_service, "_postgresql_available", lambda _: True)
    monkeypatch.setattr(health_service, "_qdrant_available", lambda _: False)
    monkeypatch.setattr(health_service, "_object_storage_available", lambda _: True)

    result = health_service.infrastructure_health(settings)

    assert result.postgresql is True
    assert result.qdrant is False
    assert result.object_storage is True
    assert result.available is False


def test_health_response_marks_a_single_dependency_failure_as_degraded(monkeypatch) -> None:
    monkeypatch.setattr(
        system,
        "infrastructure_health",
        lambda _: health_service.InfrastructureHealth(
            postgresql=True,
            qdrant=False,
            object_storage=True,
        ),
    )

    result = system.health(Settings())

    assert result.status == "degraded"
    assert result.infrastructure.model_dump() == {
        "postgresql": True,
        "qdrant": False,
        "object_storage": True,
    }


def test_container_healthcheck_requires_the_exact_live_contract() -> None:
    payload = {
        "status": "ok",
        "api_contract_version": API_CONTRACT_VERSION,
        "capabilities": list(API_CAPABILITIES),
    }

    assert health_payload_is_valid(payload) is True
    assert health_payload_is_valid({**payload, "capabilities": ["paper_jobs_v1"]}) is False
