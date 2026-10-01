from datetime import datetime
from typing import LiteralString

import procrastinate
import psycopg
from psycopg.rows import class_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from src.repositories.protocols import JobRow
from src.schemas import FuelResult, JobSubmission

_ROW: LiteralString = """
    SELECT r.job_id AS id, r.type, r.airline, r.flight_id, j.status AS queue_status, j.attempts,
           r.submitted_at, r.finished_at, r.result, r.error
    FROM job_records r JOIN procrastinate_jobs j ON j.id = r.job_id
    WHERE r.airline = %(airline)s
"""
_NEWEST_FIRST: LiteralString = " ORDER BY r.submitted_at DESC, r.job_id DESC LIMIT %(limit)s"


class PostgresJobStore:
    """`job_records` joined with Procrastinate's `procrastinate_jobs`, the one source of status."""

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

    def submit(
        self,
        submission: JobSubmission,
        plan_key: str,
        submitted_at: datetime,
        *,
        queue: str,
        queueing_lock: str,
    ) -> int:
        plan = submission.payload

        # `connection=conn` runs the defer on this connection, inside this transaction (D3).
        with self._pool.connection() as conn, conn.transaction():
            job_id = self._queue.configure_task(
                submission.type, queue=queue, queueing_lock=queueing_lock, connection=conn
            ).defer(flight_plan=plan.model_dump(mode="json"))

            conn.execute(
                """
                INSERT INTO job_records
                    (job_id, airline, type, flight_id, plan_key, submitted_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (job_id, plan.airline, submission.type, plan.flight_id, plan_key, submitted_at),
            )

        return job_id

    def get(self, airline: str, job_id: int) -> JobRow | None:
        rows = self._rows(_ROW + " AND r.job_id = %(job_id)s", airline=airline, job_id=job_id)
        return rows[0] if rows else None

    def recent(self, airline: str, limit: int) -> list[JobRow]:
        return self._rows(_ROW + _NEWEST_FIRST, airline=airline, limit=limit)

    def queued(self, airline: str, plan_key: str) -> JobRow | None:
        rows = self._rows(
            _ROW + " AND r.plan_key = %(plan_key)s AND j.status = 'todo'" + _NEWEST_FIRST,
            airline=airline,
            plan_key=plan_key,
            limit=1,
        )
        return rows[0] if rows else None

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

    def _rows(self, query: LiteralString, **params: object) -> list[JobRow]:
        with self._pool.connection() as conn, conn.cursor(row_factory=class_row(JobRow)) as cur:
            return cur.execute(query, params).fetchall()
