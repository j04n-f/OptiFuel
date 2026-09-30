from collections.abc import Mapping
from hashlib import sha256

from optifuel.clients.clock import Clock
from optifuel.config import Tenant
from optifuel.repositories.protocols import JobRepository
from optifuel.schemas import JobSubmission, JobView


class UnknownAirlineError(Exception):
    """Caller named no airline, or one that is not configured."""


class AirlineMismatchError(Exception):
    """The plan belongs to another airline than the caller."""


class AircraftNotEnabledError(Exception):
    """The plan's aircraft type is not enabled for the caller's airline."""


class JobService:
    """API side of jobs, scoped to the calling airline."""

    def __init__(self, jobs: JobRepository, clock: Clock, tenants: Mapping[str, Tenant]) -> None:
        self._jobs = jobs
        self._clock = clock
        self._tenants = tenants

    def authenticate(self, airline: str | None) -> str:
        if airline is None or airline not in self._tenants:
            raise UnknownAirlineError(f"unknown airline: {airline!r}")
        return airline

    def submit(self, airline: str, submission: JobSubmission) -> int:
        plan = submission.payload
        if plan.airline != airline:
            raise AirlineMismatchError(f"plan airline {plan.airline!r} is not {airline!r}")
        if plan.aircraft_type not in self._tenants[airline].aircraft_types:
            raise AircraftNotEnabledError(f"aircraft type {plan.aircraft_type!r} not enabled")
        # Hashed before departure_time defaults, so a retried POST without one finds its job.
        plan_key = sha256(submission.model_dump_json().encode()).hexdigest()
        latest = self._jobs.latest(airline, plan_key)
        if latest is not None and latest.status != "failed":
            return latest.id
        now = self._clock.now()
        if plan.departure_time is None:
            # Received time, not worker pick-up time: queue latency would shift every ETA.
            plan = plan.model_copy(update={"departure_time": now})
            submission = submission.model_copy(update={"payload": plan})
        return self._jobs.submit(submission, plan_key, submitted_at=now)

    def get(self, airline: str, job_id: int) -> JobView | None:
        return self._jobs.get(airline, job_id)

    def recent(self, airline: str, limit: int) -> list[JobView]:
        return self._jobs.recent(airline, limit)
