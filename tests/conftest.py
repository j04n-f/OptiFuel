from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from typing import Any

import procrastinate
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from procrastinate.testing import InMemoryConnector
from pydantic import SecretStr

from src.api import create_app
from src.clients.weather import Wind, WindQuery
from src.config import Settings, Tenant
from src.controllers.deps import get_job_queue
from src.repositories.protocols import JobRow
from src.schemas import FuelModel, FuelResult, JobSubmission
from src.services.fuel import FuelService
from src.services.jobs import JobQueue, queue_app, queue_name, register_fuel_estimate

ABC_MODEL = FuelModel.model_validate(
    {
        "airline": "ABC",
        "version": "2026-09-30",
        "form": "power_law",
        "coefficients": {"ln_c": 12.75604, "speed": 1.00009, "altitude": -1.99912},
        "envelope": {"speed_kmh": [24, 238], "altitude_ft": [1000, 10000]},
    }
)
XYZ_MODEL = ABC_MODEL.model_copy(update={"airline": "XYZ"})
MODELS = {"ABC": ABC_MODEL, "XYZ": XYZ_MODEL}
TENANTS = {
    "ABC": Tenant(aircraft_types=frozenset({"B777"}), model_version="2026-09-30"),
    "XYZ": Tenant(aircraft_types=frozenset({"A320"}), model_version="2026-09-30"),
}
DEPARTURE = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)


def flight_plan(*waypoints: dict[str, float], **overrides: object) -> dict[str, object]:
    """`POST /v1/jobs` body for an ABC B777; `overrides` replace payload fields."""
    return {
        "type": "fuel_estimate",
        "payload": {
            "airline": "ABC",
            "aircraft_type": "B777",
            "registration": "EC-ABC",
            "flight_id": 123,
            "departure_time": DEPARTURE.isoformat(),
            "route": list(waypoints),
            **overrides,
        },
    }


def waypoint(latitude: float, longitude: float, speed: float, altitude: float) -> dict[str, float]:
    return {"latitude": latitude, "longitude": longitude, "speed": speed, "altitude": altitude}


IN_ENVELOPE = waypoint(0, 0, 200, 5000)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


class FakeWeather:
    """Raises the next of `failures` per call, then answers `wind` (default calm);
    records each batched call."""

    def __init__(self) -> None:
        self.calls: list[list[WindQuery]] = []
        self.failures: list[Exception] = []
        self.wind = Wind(speed_kt=0, from_deg=0)

    def winds(self, points: Sequence[WindQuery]) -> list[Wind]:
        self.calls.append(list(points))
        if self.failures:
            raise self.failures.pop(0)
        return [self.wind] * len(points)


class InMemoryJobStore:
    """Job records in a dict; queue state comes from the in-memory connector's jobs, as the
    Postgres store's comes from `procrastinate_jobs`."""

    def __init__(self, queue: procrastinate.App, connector: InMemoryConnector) -> None:
        self._queue = queue
        self._connector = connector
        self.records: dict[int, dict[str, Any]] = {}
        self.database_up = True

    def ping(self) -> bool:
        return self.database_up

    def submit(
        self,
        submission: JobSubmission,
        plan_key: str,
        submitted_at: datetime,
        *,
        queue: str,
        queueing_lock: str,
    ) -> int:
        plan = submission.payload
        job_id = self._queue.configure_task(
            submission.type, queue=queue, queueing_lock=queueing_lock
        ).defer(flight_plan=plan.model_dump(mode="json"))
        self.records[job_id] = {
            "id": job_id,
            "type": submission.type,
            "airline": plan.airline,
            "flight_id": plan.flight_id,
            "plan_key": plan_key,
            "submitted_at": submitted_at,
        }
        return job_id

    def get(self, airline: str, job_id: int) -> JobRow | None:
        record = self.records.get(job_id)
        return self._row(record) if record and record["airline"] == airline else None

    def recent(self, airline: str, limit: int) -> list[JobRow]:
        return self._rows(airline)[:limit]

    def queued(self, airline: str, plan_key: str) -> JobRow | None:
        return next(
            (
                row
                for row in self._rows(airline)
                if self.records[row.id]["plan_key"] == plan_key and row.queue_status == "todo"
            ),
            None,
        )

    def record_success(self, job_id: int, result: FuelResult, finished_at: datetime) -> None:
        self.records[job_id] |= {"result": result, "error": None, "finished_at": finished_at}

    def record_error(self, job_id: int, error: str, finished_at: datetime) -> None:
        self.records[job_id] |= {"error": error, "finished_at": finished_at}

    def _rows(self, airline: str) -> list[JobRow]:
        own = [self._row(r) for r in self.records.values() if r["airline"] == airline]
        return sorted(own, key=lambda row: (row.submitted_at, row.id), reverse=True)

    def _row(self, record: dict[str, Any]) -> JobRow:
        job = self._connector.jobs[record["id"]]
        fields = {k: v for k, v in record.items() if k != "plan_key"}
        return JobRow(**fields, queue_status=job["status"], attempts=job["attempts"])


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 9, 30, 9, 0, tzinfo=UTC))


@pytest.fixture
def weather() -> FakeWeather:
    return FakeWeather()


@pytest.fixture
def connector() -> InMemoryConnector:
    return InMemoryConnector()


@pytest.fixture
def store(connector: InMemoryConnector) -> Iterator[InMemoryJobStore]:
    # The API side's app: defers by task name, registers no task, like `api.py`'s.
    queue = queue_app(connector)
    with queue.open():
        yield InMemoryJobStore(queue, connector)


@pytest.fixture
def run_workers(
    connector: InMemoryConnector, store: InMemoryJobStore, weather: FakeWeather, clock: FakeClock
) -> Iterator[Callable[[], None]]:
    """One worker per airline on the shared connector, each with its own model, like the
    per-airline Deployments. Calling it runs them until nothing is queued, skipping retry
    backoff by clearing `scheduled_at`: the queue's clock jumps, the retry strategy does not."""
    with ExitStack() as stack:
        workers = {}
        for airline, model in MODELS.items():
            app = stack.enter_context(queue_app(connector).open())
            register_fuel_estimate(app, FuelService(model, weather, store, clock))
            workers[airline] = app

        def run() -> None:
            while any(job["status"] == "todo" for job in connector.jobs.values()):
                for job in connector.jobs.values():
                    job["scheduled_at"] = None
                for airline, app in workers.items():
                    app.run_worker(queues=[queue_name(airline)], wait=False)

        yield run


@pytest.fixture
def app(clock: FakeClock, store: InMemoryJobStore) -> FastAPI:
    # Builds the real pool and queue, which never connect: min_size=0 and the job queue is
    # overridden with one over the in-memory store.
    settings = Settings(
        environment="dev", database_url=SecretStr("postgresql://x"), tenants=TENANTS
    )
    app = create_app(settings)

    # Typed provider, not a lambda: dependency_overrides values are unchecked, this is not.
    def in_memory_queue() -> JobQueue:
        return JobQueue(store, clock, app.state.tenants)

    app.dependency_overrides[get_job_queue] = in_memory_queue
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    """Calls as ABC; pass `headers=` per request to act as another airline."""
    with TestClient(app, headers={"X-Airline": "ABC"}) as client:
        yield client
