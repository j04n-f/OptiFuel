from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from src.schemas import FuelResult, JobSubmission


class JobRow(BaseModel):
    """A job's record joined with its queue state. `queue_status` and `attempts` are the queue's
    own words (`todo`, `doing`, ...); the job queue maps them to the contract."""

    id: int
    type: str
    airline: str
    flight_id: int
    queue_status: str
    attempts: int
    submitted_at: datetime
    finished_at: datetime | None = None
    result: FuelResult | None = None
    error: str | None = None


class JobStore(Protocol):
    """Jobs and their records. Every read is scoped to one airline: another airline's job does
    not exist for it."""

    def ping(self) -> bool:
        """Whether the store answers now: readiness, not liveness."""
        ...

    def submit(
        self,
        submission: JobSubmission,
        plan_key: str,
        submitted_at: datetime,
        *,
        queue: str,
        queueing_lock: str,
    ) -> int:
        """Defer the job to `queue` and record it, atomically; returns the job id. Raises
        Procrastinate's `AlreadyEnqueued` while another job holding `queueing_lock` is queued."""
        ...

    def get(self, airline: str, job_id: int) -> JobRow | None: ...

    def recent(self, airline: str, limit: int) -> list[JobRow]:
        """Newest submitted first."""
        ...

    def queued(self, airline: str, plan_key: str) -> JobRow | None:
        """The airline's job for this plan that is still waiting in the queue, if any."""
        ...

    def record_success(self, job_id: int, result: FuelResult, finished_at: datetime) -> None: ...

    def record_error(self, job_id: int, error: str, finished_at: datetime) -> None: ...
