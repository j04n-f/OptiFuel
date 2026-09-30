from datetime import datetime
from typing import LiteralString

import procrastinate
import psycopg
from procrastinate.exceptions import AlreadyEnqueued
from psycopg.rows import class_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from src.schemas import FuelResult, JobSubmission, JobView


def queue_name(airline: str) -> str:
    """One queue per airline: its worker listens to it alone."""
    return f"airline.{airline}"


def queue_app(connector: procrastinate.BaseConnector) -> procrastinate.App:
    # Built here, not in `worker.py`: that runs as `__main__`, where Procrastinate warns that
    # tasks named by import path break. Ours are named explicitly, so the warning is noise.
    return procrastinate.App(connector=connector)


# Status has one source, procrastinate_jobs. Its `attempts` counts finished tries, so a running
# job also counts the one in progress.
_VIEW: LiteralString = """
    SELECT r.job_id AS id, r.type, r.airline, r.flight_id,
           CASE j.status WHEN 'todo' THEN 'queued' WHEN 'doing' THEN 'running'
                ELSE j.status::text END AS status,
           j.attempts + (j.status = 'doing')::int AS attempts,
           r.submitted_at, r.finished_at, r.result, r.error
    FROM job_records r JOIN procrastinate_jobs j ON j.id = r.job_id
    WHERE r.airline = %(airline)s
"""
_NEWEST_FIRST: LiteralString = " ORDER BY r.submitted_at DESC, r.job_id DESC LIMIT %(limit)s"


class PostgresJobRepository:
    """API side: defers to the airline's queue and records the job in one transaction."""

    def __init__(self, pool: ConnectionPool, queue: procrastinate.App) -> None:
        self._pool = pool
        self._queue = queue

    def ping(self) -> bool:
        try:
            # Short wait: a probe must answer before its own timeout, not the pool's 30 s.
            with self._pool.connection(timeout=2) as conn:
                conn.execute("SELECT 1")
        except psycopg.Error:
            return False
        return True

    def submit(self, submission: JobSubmission, plan_key: str, submitted_at: datetime) -> int:
        plan = submission.payload
        try:
            with self._pool.connection() as conn, conn.transaction():
                job_id = self._queue.configure_task(
                    submission.type,
                    queue=queue_name(plan.airline),
                    queueing_lock=f"{plan.airline}:{plan_key}",
                    connection=conn,
                ).defer(flight_plan=plan.model_dump(mode="json"))
                conn.execute(
                    """
                    INSERT INTO job_records
                        (job_id, airline, type, flight_id, plan_key, submitted_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (job_id, plan.airline, submission.type, plan.flight_id, plan_key, submitted_at),
                )
        except AlreadyEnqueued:
            # An identical plan raced this one and is still queued; its record committed with it.
            existing = self.latest(plan.airline, plan_key)
            if existing is None:
                raise
            return existing.id
        return job_id

    def latest(self, airline: str, plan_key: str) -> JobView | None:
        views = self._views(
            _VIEW + " AND r.plan_key = %(plan_key)s" + _NEWEST_FIRST,
            airline=airline,
            plan_key=plan_key,
            limit=1,
        )
        return views[0] if views else None

    def get(self, airline: str, job_id: int) -> JobView | None:
        views = self._views(_VIEW + " AND r.job_id = %(job_id)s", airline=airline, job_id=job_id)
        return views[0] if views else None

    def recent(self, airline: str, limit: int) -> list[JobView]:
        return self._views(_VIEW + _NEWEST_FIRST, airline=airline, limit=limit)

    def _views(self, query: LiteralString, **params: object) -> list[JobView]:
        with self._pool.connection() as conn, conn.cursor(row_factory=class_row(JobView)) as cur:
            return cur.execute(query, params).fetchall()


class PostgresResultRepository:
    """Worker side: writes the outcome of an attempt onto the job's record."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool

    def record_success(self, job_id: int, result: FuelResult, finished_at: datetime) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE job_records SET result = %s, error = NULL, finished_at = %s"
                " WHERE job_id = %s",
                (Jsonb(result.model_dump()), finished_at, job_id),
            )

    def record_error(self, job_id: int, error: str, finished_at: datetime) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE job_records SET error = %s, finished_at = %s WHERE job_id = %s",
                (error, finished_at, job_id),
            )
