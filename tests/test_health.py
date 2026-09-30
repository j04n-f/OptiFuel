import pytest
from fastapi.testclient import TestClient

from tests.conftest import InMemoryJobStore


def test_reports_process_up(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(("database_up", "status"), [(True, 200), (False, 503)])
def test_reports_ready_only_when_database_answers(
    client: TestClient, store: InMemoryJobStore, database_up: bool, status: int
) -> None:
    store.database_up = database_up

    response = client.get("/ready")

    assert response.status_code == status
