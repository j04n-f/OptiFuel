from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from tests.conftest import FakeClock, FakeWeather

DEPARTURE = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)


def flight_plan(*waypoints: dict[str, float], **overrides: object) -> dict[str, object]:
    return {
        "type": "fuel_estimate",
        "payload": {
            "airline": "ABC",
            "aircraft_type": "B777",
            "registration": "EC-ABC",
            "flight_id": 123,
            "departure_time": DEPARTURE.isoformat(),
            "waypoints": list(waypoints),
            **overrides,
        },
    }


def waypoint(latitude: float, longitude: float, speed: float, altitude: float) -> dict[str, float]:
    return {"latitude": latitude, "longitude": longitude, "speed": speed, "altitude": altitude}


def test_estimates_route_fuel(client: TestClient, weather: FakeWeather) -> None:
    plan = flight_plan(
        waypoint(0, 0, 200, 5000), waypoint(1, 0, 150, 4000), waypoint(1, 1, 150, 4000)
    )

    submitted = client.post("/v1/jobs", json=plan)
    job = client.get(f"/v1/jobs/{submitted.json()['id']}").json()

    assert submitted.status_code == 202
    assert job["status"] == "succeeded"
    assert job["flight_id"] == 123
    assert job["error"] is None
    assert job["result"] == {
        "total_fuel_lb": pytest.approx(3.98041, rel=1e-5),
        "distance_km": pytest.approx(222.373, rel=1e-5),
        "duration_h": pytest.approx(1.29716, rel=1e-5),
        "model_version": "2026-09-30",
    }
    [asked] = weather.calls
    assert [(q.latitude, q.longitude, q.altitude_ft) for q in asked] == [
        (0, 0, 5000),
        (1, 0, 4000),
        (1, 1, 4000),
    ]
    assert [(q.eta - DEPARTURE).total_seconds() for q in asked] == pytest.approx(
        [0, 2001.51, 4669.78], abs=0.01
    )


def test_departs_at_received_time_by_default(
    client: TestClient, weather: FakeWeather, clock: FakeClock
) -> None:
    plan = flight_plan(waypoint(0, 0, 200, 5000), waypoint(1, 0, 200, 5000), departure_time=None)

    submitted = client.post("/v1/jobs", json=plan)
    job = client.get(f"/v1/jobs/{submitted.json()['id']}").json()

    assert job["status"] == "succeeded"
    assert job["submitted_at"] == "2026-09-30T09:00:00Z"
    [asked] = weather.calls
    assert asked[0].eta == clock.current


def test_fails_out_of_envelope_plan(client: TestClient) -> None:
    plan = flight_plan(
        waypoint(0, 0, 200, 5000), waypoint(1, 0, 200, 35000), waypoint(1, 1, 300, 5000)
    )

    submitted = client.post("/v1/jobs", json=plan)
    job = client.get(f"/v1/jobs/{submitted.json()['id']}").json()

    assert job["status"] == "failed"
    assert job["result"] is None
    assert job["error"] == "out_of_envelope: waypoints 1, 2"


def test_records_error_when_weather_fails(client: TestClient, weather: FakeWeather) -> None:
    weather.error = TimeoutError("weather API timed out")
    plan = flight_plan(waypoint(0, 0, 200, 5000), waypoint(1, 0, 200, 5000))

    submitted = client.post("/v1/jobs", json=plan)
    job = client.get(f"/v1/jobs/{submitted.json()['id']}").json()

    assert job["status"] == "failed"
    assert job["result"] is None
    assert job["error"] == "TimeoutError: weather API timed out"


VALID = waypoint(0, 0, 200, 5000)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("waypoints", [VALID]),
        ("waypoints", [VALID, {**VALID, "latitude": 90.1}]),
        ("waypoints", [VALID, {**VALID, "longitude": -180.1}]),
        ("waypoints", [VALID, {**VALID, "speed": 0}]),
        ("waypoints", [VALID, {**VALID, "altitude": -1}]),
        ("departure_time", "2026-09-30T10:00:00"),
        ("registration", ""),
    ],
)
def test_rejects_invalid_flight_plan(client: TestClient, field: str, value: object) -> None:
    plan = flight_plan(VALID, VALID, **{field: value})

    response = client.post("/v1/jobs", json=plan)

    assert response.status_code == 422
