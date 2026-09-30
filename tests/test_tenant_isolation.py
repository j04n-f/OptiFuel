from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.conftest import IN_ENVELOPE, FakeClock, flight_plan

V = IN_ENVELOPE
XYZ = {"X-Airline": "XYZ"}


def test_hides_other_airlines_jobs(client: TestClient) -> None:
    submitted = client.post("/v1/jobs", json=flight_plan(V, V))

    response = client.get(f"/v1/jobs/{submitted.json()['id']}", headers=XYZ)

    assert response.status_code == 404


def test_lists_own_jobs_newest_first(client: TestClient, clock: FakeClock) -> None:
    older = client.post("/v1/jobs", json=flight_plan(V, V, flight_id=1)).json()["id"]
    clock.current += timedelta(minutes=1)
    xyz_plan = flight_plan(V, V, airline="XYZ", aircraft_type="A320")
    client.post("/v1/jobs", json=xyz_plan, headers=XYZ)
    clock.current += timedelta(minutes=1)
    newer = client.post("/v1/jobs", json=flight_plan(V, V, flight_id=2)).json()["id"]

    response = client.get("/v1/jobs")

    assert response.status_code == 200
    assert [(job["id"], job["flight_id"]) for job in response.json()] == [(newer, 2), (older, 1)]


def test_lists_configured_airlines_without_identity(app: FastAPI) -> None:
    with TestClient(app) as anonymous:
        response = anonymous.get("/v1/tenants")

    assert response.status_code == 200
    assert response.json() == ["ABC", "XYZ"]
