from datetime import datetime
from typing import Protocol

from optifuel.schemas import FuelResult, JobSubmission, JobView


class JobRepository(Protocol):
    """Every read is scoped to one airline: another airline's job does not exist for it."""

    def ping(self) -> bool:
        """Whether the store answers now: readiness, not liveness."""
        ...

    def submit(self, submission: JobSubmission, plan_key: str, submitted_at: datetime) -> int:
        """Queue the job and record it; returns the job id. A concurrent submit with the same
        airline and `plan_key` returns the job the other one queued."""
        ...

    def latest(self, airline: str, plan_key: str) -> JobView | None:
        """The airline's newest job for this plan, whatever its status."""
        ...

    def get(self, airline: str, job_id: int) -> JobView | None: ...

    def recent(self, airline: str, limit: int) -> list[JobView]:
        """Newest submitted first."""
        ...


class ResultRepository(Protocol):
    def record_success(self, job_id: int, result: FuelResult, finished_at: datetime) -> None: ...

    def record_error(self, job_id: int, error: str, finished_at: datetime) -> None: ...
