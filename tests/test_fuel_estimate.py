from collections.abc import Callable
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

NORTHBOUND = (waypoint(0, 0, 200, 5000), waypoint(1, 0, 200, 5000))


def test_estimates_route_fuel(
    client: TestClient, weather: FakeWeather, run_workers: Callable[[], None]
) -> None:
    plan = flight_plan(
        waypoint(0, 0, 200, 5000), waypoint(1, 0, 150, 4000), waypoint(1, 1, 150, 4000)
    )

    submitted = client.post("/v1/jobs", json=plan)
    run_workers()
    job = client.get(f"/v1/jobs/{submitted.json()['id']}").json()

    assert submitted.status_code == 202
    assert job["status"] == "succeeded"
    assert job["attempts"] == 1
    assert job["flight_id"] == 123
    assert job["error"] is None
    assert job["result"] == {
        "total_fuel_lb": pytest.approx(3.98153, rel=1e-5),
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


def test_shows_job_queued_until_a_worker_claims_it(
    client: TestClient, run_workers: Callable[[], None]
) -> None:
    submitted = client.post("/v1/jobs", json=flight_plan(*NORTHBOUND))

    queued = client.get(f"/v1/jobs/{submitted.json()['id']}").json()
    run_workers()
    done = client.get(f"/v1/jobs/{submitted.json()['id']}").json()

    assert (queued["status"], queued["attempts"], queued["result"]) == ("queued", 0, None)
    assert (done["status"], done["attempts"]) == ("succeeded", 1)


def test_departs_at_received_time_by_default(
    client: TestClient,
    weather: FakeWeather,
    clock: FakeClock,
    run_workers: Callable[[], None],
) -> None:
    plan = flight_plan(*NORTHBOUND, departure_time=None)

    submitted = client.post("/v1/jobs", json=plan)
    run_workers()
    job = client.get(f"/v1/jobs/{submitted.json()['id']}").json()

    assert job["status"] == "succeeded"
    assert job["submitted_at"] == "2026-09-30T09:00:00Z"
    [asked] = weather.calls
    assert asked[0].eta == clock.current


def test_headwind_raises_fuel_over_calm_air(
    client: TestClient, weather: FakeWeather, run_workers: Callable[[], None]
) -> None:
    calm = client.post("/v1/jobs", json=flight_plan(*NORTHBOUND, flight_id=1)).json()["id"]
    run_workers()
    weather.wind = Wind(speed_kt=20, from_deg=0)

    against = client.post("/v1/jobs", json=flight_plan(*NORTHBOUND, flight_id=2)).json()["id"]
    run_workers()

    still = client.get(f"/v1/jobs/{calm}").json()["result"]
    headwind = client.get(f"/v1/jobs/{against}").json()["result"]
    # Ground speed drops from 200 to 200 - 20 kt * 1.852 = 162.96 km/h over the same distance.
    assert headwind["total_fuel_lb"] == pytest.approx(still["total_fuel_lb"] * 200 / 162.96)
    assert headwind["distance_km"] == still["distance_km"]


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
            "internal_error",
            True,
            id="bad weather reply",
        ),
    ],
)
def test_fails_permanent_error_on_first_attempt(
    client: TestClient,
    weather: FakeWeather,
    run_workers: Callable[[], None],
    plan: dict[str, object],
    failures: list[Exception],
    error: str,
    calls_weather: bool,
) -> None:
    weather.failures = list(failures)

    submitted = client.post("/v1/jobs", json=plan)
    run_workers()
    job = client.get(f"/v1/jobs/{submitted.json()['id']}").json()

    assert job["status"] == "failed"
    assert job["attempts"] == 1
    assert job["result"] is None
    assert job["error"] == error
    if calls_weather:
        assert len(weather.calls) == 1
    else:
        assert weather.calls == []


def test_fails_on_non_positive_ground_speed(
    client: TestClient, weather: FakeWeather, run_workers: Callable[[], None]
) -> None:
    # Northbound leg: wind from 0° is a headwind, and 200 kt exceeds 200 km/h airspeed.
    weather.wind = Wind(speed_kt=200, from_deg=0)

    submitted = client.post("/v1/jobs", json=flight_plan(*NORTHBOUND))
    run_workers()
    job = client.get(f"/v1/jobs/{submitted.json()['id']}").json()

    assert job["status"] == "failed"
    assert job["attempts"] == 1
    assert "non_positive_ground_speed" in job["error"]
    assert len(weather.calls) == 1


def test_fails_after_three_attempts_while_weather_is_unavailable(
    client: TestClient, weather: FakeWeather, run_workers: Callable[[], None]
) -> None:
    weather.failures = [
        WeatherUnavailableError(f"weather API answered {s}") for s in (503, 502, 504)
    ]

    submitted = client.post("/v1/jobs", json=flight_plan(IN_ENVELOPE, IN_ENVELOPE))
    run_workers()
    job = client.get(f"/v1/jobs/{submitted.json()['id']}").json()

    assert job["status"] == "failed"
    assert job["attempts"] == 3
    assert job["result"] is None
    assert job["error"] == "weather_unavailable"
    assert len(weather.calls) == 3


def test_succeeds_on_retry_once_weather_recovers(
    client: TestClient, weather: FakeWeather, run_workers: Callable[[], None]
) -> None:
    weather.failures = [WeatherUnavailableError("weather API answered 503")]

    submitted = client.post("/v1/jobs", json=flight_plan(IN_ENVELOPE, IN_ENVELOPE))
    run_workers()
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
        pytest.param(ABC, flight_plan(*[V] * 501), 422, id="501 waypoints"),
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
    app: FastAPI,
    weather: FakeWeather,
    run_workers: Callable[[], None],
    headers: dict[str, str],
    body: object,
    status: int,
) -> None:
    with TestClient(app, headers=headers) as client:
        response = client.post("/v1/jobs", json=body)
        run_workers()
        listed = client.get("/v1/jobs", headers=ABC).json()

    assert response.status_code == status
    assert listed == []
    assert weather.calls == []


@pytest.mark.parametrize(
    ("first_departure", "again_departure"),
    [
        pytest.param("2026-09-30T10:00:00Z", "2026-09-30T10:00:00Z", id="same departure"),
        pytest.param(None, None, id="departs when received"),
        pytest.param("2026-09-30T10:00:00Z", "2026-09-30T12:00:00+02:00", id="same instant"),
    ],
)
def test_returns_queued_job_for_resubmitted_plan(
    client: TestClient,
    weather: FakeWeather,
    clock: FakeClock,
    run_workers: Callable[[], None],
    first_departure: str | None,
    again_departure: str | None,
) -> None:
    first = client.post("/v1/jobs", json=flight_plan(V, V, departure_time=first_departure))
    clock.current += timedelta(hours=1)

    again = client.post("/v1/jobs", json=flight_plan(V, V, departure_time=again_departure))
    run_workers()

    assert again.status_code == 202
    assert again.json() == first.json()
    assert len(client.get("/v1/jobs").json()) == 1
    assert len(weather.calls) == 1


@pytest.mark.parametrize(
    ("failures", "earlier_status"),
    [
        pytest.param([], "succeeded", id="succeeded"),
        pytest.param([ValueError("malformed weather reply")], "failed", id="failed"),
    ],
)
def test_queues_new_job_once_same_plan_was_claimed(
    client: TestClient,
    weather: FakeWeather,
    run_workers: Callable[[], None],
    failures: list[Exception],
    earlier_status: str,
) -> None:
    plan = flight_plan(V, V)
    weather.failures = list(failures)
    earlier = client.post("/v1/jobs", json=plan).json()["id"]
    run_workers()

    again = client.post("/v1/jobs", json=plan).json()["id"]
    run_workers()

    assert again != earlier
    assert client.get(f"/v1/jobs/{earlier}").json()["status"] == earlier_status
    assert client.get(f"/v1/jobs/{again}").json()["status"] == "succeeded"
