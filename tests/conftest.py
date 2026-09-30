from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from optifuel.api import create_app
from optifuel.clients.clock import Clock
from optifuel.clients.weather import Wind, WindQuery
from optifuel.config import Settings
from optifuel.controllers.deps import get_clock, get_job_repository
from optifuel.repositories.protocols import JobRepository
from optifuel.schemas import FuelModel, FuelResult, JobSubmission, JobView
from optifuel.services.fuel import FuelService

ABC_MODEL = FuelModel.model_validate(
    {
        "airline": "ABC",
        "version": "2026-09-30",
        "form": "power_law",
        "coefficients": {"ln_c": 12.75644, "speed": 0.99981, "altitude": -1.99903},
        "envelope": {"speed_kmh": [24, 238], "altitude_ft": [1000, 10000]},
    }
)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current


class FakeWeather:
    """Answers calm air for every point, or raises `error` if set; records each batched call."""

    def __init__(self) -> None:
        self.calls: list[list[WindQuery]] = []
        self.error: Exception | None = None

    def winds(self, points: Sequence[WindQuery]) -> list[Wind]:
        self.calls.append(list(points))
        if self.error is not None:
            raise self.error
        return [Wind(speed_kt=0, from_deg=0)] * len(points)


class FakeJobs:
    """Job and result store in one dict; `submit` runs the airline's worker inline, like a queue
    whose worker claims the job at once and, with no retries configured, fails it on any error."""

    def __init__(self) -> None:
        self.jobs: dict[int, JobView] = {}
        self.workers: dict[str, FuelService] = {}

    def submit(self, submission: JobSubmission, submitted_at: datetime) -> int:
        plan = submission.payload
        job = JobView(
            id=len(self.jobs) + 1,
            type=submission.type,
            airline=plan.airline,
            flight_id=plan.flight_id,
            status="running",
            attempts=1,
            submitted_at=submitted_at,
        )
        self.jobs[job.id] = job
        try:
            self.workers[plan.airline].estimate(job.id, plan)
        except Exception:  # Procrastinate fails the attempt on any exception
            job.status = "failed"
        else:
            job.status = "succeeded"
        return job.id

    def get(self, job_id: int) -> JobView | None:
        return self.jobs.get(job_id)

    def record_success(self, job_id: int, result: FuelResult, finished_at: datetime) -> None:
        job = self.jobs[job_id]
        job.result, job.error, job.finished_at = result, None, finished_at

    def record_error(self, job_id: int, error: str, finished_at: datetime) -> None:
        job = self.jobs[job_id]
        job.error, job.finished_at = error, finished_at


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 9, 30, 9, 0, tzinfo=UTC))


@pytest.fixture
def weather() -> FakeWeather:
    return FakeWeather()


@pytest.fixture
def jobs(clock: FakeClock, weather: FakeWeather) -> FakeJobs:
    jobs = FakeJobs()
    jobs.workers["ABC"] = FuelService(ABC_MODEL, weather, jobs, clock)
    return jobs


@pytest.fixture
def app(clock: FakeClock, jobs: FakeJobs) -> FastAPI:
    # Typed providers, not lambdas: dependency_overrides values are unchecked, these are not.
    def fake_clock() -> Clock:
        return clock

    def fake_jobs() -> JobRepository:
        return jobs

    app = create_app(Settings(environment="dev"))
    app.dependency_overrides[get_clock] = fake_clock
    app.dependency_overrides[get_job_repository] = fake_jobs
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client
