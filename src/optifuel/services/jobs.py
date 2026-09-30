from optifuel.clients.clock import Clock
from optifuel.repositories.protocols import JobRepository
from optifuel.schemas import JobSubmission, JobView


# ponytail: no tenant scope yet, so any caller submits for and reads any airline. The X-Airline
# checks (401/403, disabled aircraft 422, other airline's job 404) land in this service.
class JobService:
    def __init__(self, jobs: JobRepository, clock: Clock) -> None:
        self._jobs = jobs
        self._clock = clock

    def submit(self, submission: JobSubmission) -> int:
        now = self._clock.now()
        plan = submission.payload
        if plan.departure_time is None:
            # Received time, not worker pick-up time: queue latency would shift every ETA.
            plan = plan.model_copy(update={"departure_time": now})
            submission = submission.model_copy(update={"payload": plan})
        return self._jobs.submit(submission, submitted_at=now)

    def get(self, job_id: int) -> JobView | None:
        return self._jobs.get(job_id)
