from hashlib import sha256

from src.clients.clock import Clock
from src.repositories.protocols import JobRepository
from src.schemas import JobSubmission, JobView
from src.services.tenants import Tenants


class AirlineMismatchError(Exception):
    """The plan belongs to another airline than the caller."""


class JobService:
    """API side of jobs, scoped to the calling airline."""

    def __init__(self, jobs: JobRepository, clock: Clock, tenants: Tenants) -> None:
        self._jobs = jobs
        self._clock = clock
        self._tenants = tenants

    def ready(self) -> bool:
        return self._jobs.ping()

    def submit(self, airline: str, submission: JobSubmission) -> int:
        plan = submission.payload
        if plan.airline != airline:
            raise AirlineMismatchError(f"plan airline {plan.airline!r} is not {airline!r}")
        self._tenants.check_aircraft(airline, plan.aircraft_type)
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
