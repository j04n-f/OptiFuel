from datetime import datetime
from typing import Protocol

from optifuel.schemas import FuelResult, JobSubmission, JobView


class JobRepository(Protocol):
    def submit(self, submission: JobSubmission, submitted_at: datetime) -> int:
        """Queue the job and record it; returns the job id."""
        ...

    def get(self, job_id: int) -> JobView | None: ...


class ResultRepository(Protocol):
    def record_success(self, job_id: int, result: FuelResult, finished_at: datetime) -> None: ...

    def record_error(self, job_id: int, error: str, finished_at: datetime) -> None: ...
