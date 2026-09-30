"""One-shot: fake airline DEMO with one job in every status, for trying the page.

DEMO has no worker, so its queued and running jobs stay as seeded. Re-running replaces them.
The API shows them only when DEMO is in `OPTIFUEL_TENANTS`.
"""

import sys
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.types.json import Jsonb

from src.config import Settings
from src.repositories.postgres import queue_name
from src.schemas import FlightPlan, FuelResult, Waypoint

AIRLINE = "DEMO"
MODEL_VERSION = "2026-09-30"

# status, flight_id, minutes ago submitted, seconds to finish, result, error.
# The result is what the ABC model gives for this plan (the fuel scale is the simulated dataset's).
JOBS = [
    ("todo", 3004, 1, None, None, None),
    ("doing", 3003, 3, None, None, None),
    (
        "succeeded",
        3002,
        12,
        4,
        FuelResult(
            total_fuel_lb=1.21, distance_km=93.4, duration_h=0.44, model_version=MODEL_VERSION
        ),
        None,
    ),
    ("failed", 3001, 25, 1, None, "out_of_envelope: waypoints 0"),
]


def plan(flight_id: int, departure: datetime) -> FlightPlan:
    return FlightPlan(
        airline=AIRLINE,
        aircraft_type="A350",
        registration="EC-DMO",
        flight_id=flight_id,
        departure_time=departure,
        waypoints=[
            Waypoint(latitude=41.3, longitude=2.1, speed=200, altitude=5000),
            Waypoint(latitude=41.8, longitude=3.0, speed=180, altitude=4000),
        ],
    )


def main() -> None:
    settings = Settings()
    if settings.environment == "prod":
        sys.exit("seed writes fake jobs: dev only")
    now = datetime.now(UTC)
    with psycopg.connect(settings.database_url.get_secret_value()) as conn, conn.transaction():
        # Cascades to job_records.
        conn.execute("DELETE FROM procrastinate_jobs WHERE queue_name = %s", (queue_name(AIRLINE),))
        for status, flight_id, minutes_ago, took_s, result, error in JOBS:
            submitted = now - timedelta(minutes=minutes_ago)
            finished = submitted + timedelta(seconds=took_s) if took_s is not None else None
            args = {"flight_plan": plan(flight_id, submitted).model_dump(mode="json")}
            # Procrastinate's `attempts` counts finished tries; a finished job has one.
            attempts = 1 if finished else 0
            row = conn.execute(
                "INSERT INTO procrastinate_jobs (queue_name, task_name, args, status, attempts)"
                " VALUES (%s, 'fuel_estimate', %s, %s, %s) RETURNING id",
                (queue_name(AIRLINE), Jsonb(args), status, attempts),
            ).fetchone()
            if row is None:
                raise RuntimeError("INSERT ... RETURNING gave no row")
            conn.execute(
                "INSERT INTO job_records (job_id, airline, type, flight_id, plan_key,"
                " submitted_at, finished_at, result, error)"
                " VALUES (%s, %s, 'fuel_estimate', %s, %s, %s, %s, %s, %s)",
                (
                    row[0],
                    AIRLINE,
                    flight_id,
                    f"seed:{flight_id}",
                    submitted,
                    finished,
                    Jsonb(result.model_dump()) if result else None,
                    error,
                ),
            )


if __name__ == "__main__":
    main()
