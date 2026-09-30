from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.clients.weather import WeatherUnavailableError, Wind
from tests.conftest import (
    DEPARTURE,
    IN_ENVELOPE,
    FakeClock,
    FakeWeather,
    flight_plan,
    waypoint,
)


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


@pytest.mark.parametrize(
    ("plan", "failures", "error", "calls_weather"),
    [
        pytest.param(
            flight_plan(
                waypoint(0, 0, 200, 5000), waypoint(1, 0, 200, 35000), waypoint(1, 1, 300, 5000)
            ),
            [],
            "out_of_envelope: waypoints 1, 2",
            False,
            id="out of envelope",
        ),
        pytest.param(
            flight_plan(IN_ENVELOPE, IN_ENVELOPE),
            [ValueError("malformed weather reply")],
            "ValueError: malformed weather reply",
            True,
            id="bad weather reply",
        ),
    ],
)
def test_fails_permanent_error_on_first_attempt(
    client: TestClient,
    weather: FakeWeather,
    plan: dict[str, object],
    failures: list[Exception],
    error: str,
    calls_weather: bool,
) -> None:
    weather.failures = list(failures)

    submitted = client.post("/v1/jobs", json=plan)
    job = client.get(f"/v1/jobs/{submitted.json()['id']}").json()

    assert job["status"] == "failed"
    assert job["attempts"] == 1
    assert job["result"] is None
    assert job["error"] == error
    if calls_weather:
        assert len(weather.calls) == 1
    else:
        assert weather.calls == []


def test_fails_on_non_positive_ground_speed(client: TestClient, weather: FakeWeather) -> None:
    # Northbound leg: wind from 0° is a headwind, and 200 kt exceeds 200 km/h airspeed.
    weather.wind = Wind(speed_kt=200, from_deg=0)

    submitted = client.post(
        "/v1/jobs", json=flight_plan(waypoint(0, 0, 200, 5000), waypoint(1, 0, 200, 5000))
    )
    job = client.get(f"/v1/jobs/{submitted.json()['id']}").json()

    assert job["status"] == "failed"
    assert job["attempts"] == 1
    assert "non_positive_ground_speed" in job["error"]
    assert len(weather.calls) == 1


def test_fails_after_three_attempts_while_weather_is_unavailable(
    client: TestClient, weather: FakeWeather
) -> None:
    weather.failures = [
        WeatherUnavailableError(f"weather API answered {s}") for s in (503, 502, 504)
    ]

    submitted = client.post("/v1/jobs", json=flight_plan(IN_ENVELOPE, IN_ENVELOPE))
    job = client.get(f"/v1/jobs/{submitted.json()['id']}").json()

    assert job["status"] == "failed"
    assert job["attempts"] == 3
    assert job["result"] is None
    assert job["error"] == "WeatherUnavailableError: weather API answered 504"
    assert len(weather.calls) == 3


def test_succeeds_on_retry_once_weather_recovers(client: TestClient, weather: FakeWeather) -> None:
    weather.failures = [WeatherUnavailableError("weather API answered 503")]

    submitted = client.post("/v1/jobs", json=flight_plan(IN_ENVELOPE, IN_ENVELOPE))
    job = client.get(f"/v1/jobs/{submitted.json()['id']}").json()

    assert job["status"] == "succeeded"
    assert job["attempts"] == 2
    assert job["result"] is not None
    assert job["error"] is None


V = IN_ENVELOPE
ABC = {"X-Airline": "ABC"}


@pytest.mark.parametrize(
    ("headers", "body", "status"),
    [
        pytest.param({}, flight_plan(V, V), 401, id="no airline header"),
        pytest.param({"X-Airline": "QQQ"}, flight_plan(V, V), 401, id="unconfigured airline"),
        pytest.param({"X-Airline": "XYZ"}, flight_plan(V, V), 403, id="other airline's plan"),
        pytest.param(ABC, flight_plan(V, V, aircraft_type="A320"), 422, id="aircraft disabled"),
        pytest.param(ABC, {**flight_plan(V, V), "type": "other"}, 422, id="unknown job type"),
        pytest.param(ABC, flight_plan(V), 422, id="one waypoint"),
        pytest.param(ABC, flight_plan(V, {**V, "latitude": 90.1}), 422, id="latitude"),
        pytest.param(ABC, flight_plan(V, {**V, "longitude": -180.1}), 422, id="longitude"),
        pytest.param(ABC, flight_plan(V, {**V, "speed": 0}), 422, id="speed"),
        pytest.param(ABC, flight_plan(V, {**V, "altitude": -1}), 422, id="altitude"),
        pytest.param(
            ABC, flight_plan(V, V, departure_time="2026-09-30T10:00:00"), 422, id="naive time"
        ),
        pytest.param(ABC, flight_plan(V, V, registration=""), 422, id="registration"),
    ],
)
def test_rejects_invalid_submission(
    app: FastAPI, weather: FakeWeather, headers: dict[str, str], body: object, status: int
) -> None:
    with TestClient(app, headers=headers) as client:
        response = client.post("/v1/jobs", json=body)

    assert response.status_code == status
    assert weather.calls == []


@pytest.mark.parametrize(
    ("first_departure", "again_departure"),
    [
        pytest.param("2026-09-30T10:00:00Z", "2026-09-30T10:00:00Z", id="same departure"),
        pytest.param(None, None, id="departs when received"),
        pytest.param("2026-09-30T10:00:00Z", "2026-09-30T12:00:00+02:00", id="same instant"),
    ],
)
def test_returns_existing_job_for_resubmitted_plan(
    client: TestClient,
    weather: FakeWeather,
    clock: FakeClock,
    first_departure: str | None,
    again_departure: str | None,
) -> None:
    first = client.post("/v1/jobs", json=flight_plan(V, V, departure_time=first_departure))
    clock.current += timedelta(hours=1)

    again = client.post("/v1/jobs", json=flight_plan(V, V, departure_time=again_departure))

    assert again.status_code == 202
    assert again.json() == first.json()
    assert len(weather.calls) == 1


def test_queues_new_job_when_same_plan_failed(client: TestClient, weather: FakeWeather) -> None:
    plan = flight_plan(V, V)
    weather.failures = [ValueError("malformed weather reply")]
    failed = client.post("/v1/jobs", json=plan).json()["id"]

    again = client.post("/v1/jobs", json=plan).json()["id"]

    assert again != failed
    assert client.get(f"/v1/jobs/{again}").json()["status"] == "succeeded"
