import asyncio
import logging

import procrastinate

from src.config import Settings
from src.repositories.postgres import queue_app

logger = logging.getLogger(__name__)


async def cleanup(settings: Settings) -> None:
    queue = queue_app(
        procrastinate.PsycopgConnector(conninfo=settings.database_url.get_secret_value())
    )
    async with queue.open_async():
        jobs = queue.job_manager
        # Stalled: running on a worker whose heartbeat is over 30 s old. ponytail: requeued
        # however often they stall; fail them past the retry cap if a job keeps killing workers.
        for job in await jobs.get_stalled_jobs():
            await jobs.retry_job(job)
            logger.info("requeued stalled job_id=%s queue=%s", job.id, job.queue)
        # Failed jobs too, so dead letters don't pile up; ON DELETE CASCADE drops their records.
        await jobs.delete_old_jobs(nb_hours=settings.retention_days * 24, include_failed=True)


def main() -> None:
    """One-shot: requeue jobs from dead workers, purge old finished ones."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(cleanup(Settings()))


if __name__ == "__main__":
    main()
