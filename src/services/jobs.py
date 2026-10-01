from hashlib import sha256
from typing import Any

import procrastinate
import psycopg
from procrastinate.exceptions import AlreadyEnqueued

from src.clients.clock import Clock
from src.clients.weather import WeatherUnavailableError
from src.repositories.protocols import JobRow, JobStore
from src.schemas import FlightPlan, JobStatus, JobSubmission, JobView
from src.services.fuel import FuelService
from src.services.tenants import Tenants

FUEL_ESTIMATE = "fuel_estimate"

# Retries only errors a later attempt can clear; any other one fails the job at once.
# `max_attempts` counts retries, so 2 means 3 attempts. Waits 5 s, then 25 s.
RETRY = procrastinate.RetryStrategy(
    max_attempts=2,
    exponential_wait=5,
    retry_exceptions={WeatherUnavailableError, psycopg.OperationalError},
)

# The queue's words for the contract's statuses. `cancelled` and `aborted` are unreachable:
# there is no cancel endpoint.
_STATUS: dict[str, JobStatus] = {
    "todo": "queued",
    "doing": "running",
    "succeeded": "succeeded",
    "failed": "failed",
}


class AirlineMismatchError(Exception):
    """The plan belongs to another airline than the caller."""


def queue_name(airline: str) -> str:
    """One queue per airline: its worker listens to it alone."""
    return f"airline.{airline}"


def queue_app(connector: procrastinate.BaseConnector) -> procrastinate.App:
    # Built here, not in a `__main__` module, where Procrastinate warns that tasks named by
    # import path break. Ours are named explicitly, so the warning is noise.
    return procrastinate.App(connector=connector)


def register_fuel_estimate(app: procrastinate.App, service: FuelService) -> None:
    """Worker side: the `fuel_estimate` task, bound to one airline's fuel service."""

    # Sync task: Procrastinate runs it in a thread, off the worker's event loop.
    @app.task(name=FUEL_ESTIMATE, pass_context=True, retry=RETRY)
    def fuel_estimate(context: procrastinate.JobContext, flight_plan: dict[str, Any]) -> None:
        job_id = context.job.id
        if job_id is None:
            raise ValueError("a claimed job always has an id")
        service.estimate(job_id, FlightPlan.model_validate(flight_plan))


class JobQueue:
    """API side of the job queue: submits the calling airline's jobs and views them."""

    def __init__(self, store: JobStore, clock: Clock, tenants: Tenants) -> None:
        self._store = store
        self._clock = clock
        self._tenants = tenants

    def ready(self) -> bool:
        return self._store.ping()

    def submit(self, airline: str, submission: JobSubmission) -> int:
        plan = submission.payload

        if plan.airline != airline:
            raise AirlineMismatchError(f"plan airline {plan.airline!r} is not {airline!r}")

        self._tenants.check_aircraft(airline, plan.aircraft_type)

        # Hashed before departure_time defaults, so a retried POST without one finds its job.
        plan_key = sha256(submission.model_dump_json().encode()).hexdigest()
        now = self._clock.now()

        if plan.departure_time is None:
            # Received time, not worker pick-up time: queue latency would shift every ETA.
            plan = plan.model_copy(update={"departure_time": now})
            submission = submission.model_copy(update={"payload": plan})

        try:
            return self._store.submit(
                submission,
                plan_key,
                submitted_at=now,
                queue=queue_name(airline),
                queueing_lock=f"{airline}:{plan_key}",
            )
        except AlreadyEnqueued:
            # Duplicate submission (D13): the same plan is still queued, so that job is the answer.
            queued = self._store.queued(airline, plan_key)

            if queued is None:
                raise

            return queued.id

    def get(self, airline: str, job_id: int) -> JobView | None:
        row = self._store.get(airline, job_id)
        return None if row is None else _view(row)

    def recent(self, airline: str, limit: int) -> list[JobView]:
        return [_view(row) for row in self._store.recent(airline, limit)]


def _view(row: JobRow) -> JobView:
    # The queue's `attempts` counts finished tries, so a running job also counts the one in
    # progress.
    return JobView(
        id=row.id,
        type=row.type,
        airline=row.airline,
        flight_id=row.flight_id,
        status=_STATUS[row.queue_status],
        attempts=row.attempts + (row.queue_status == "doing"),
        submitted_at=row.submitted_at,
        finished_at=row.finished_at,
        result=row.result,
        error=row.error,
    )
