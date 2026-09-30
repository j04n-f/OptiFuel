import logging
import sys
from typing import Any

import httpx2
import procrastinate
import psycopg
from psycopg_pool import ConnectionPool
from pydantic import ValidationError

from src.clients.clock import SystemClock
from src.clients.weather import HttpWeatherClient, WeatherUnavailableError
from src.config import Settings
from src.repositories.files import FileModelRepository
from src.repositories.postgres import PostgresResultRepository, queue_app, queue_name
from src.schemas import FlightPlan
from src.services.fuel import FuelService
from src.services.tenants import Tenants, UnknownAirlineError

# Retries only errors a later attempt can clear; any other one fails the job at once.
# `max_attempts` counts retries, so 2 means 3 attempts. Waits 5 s, then 25 s.
RETRY = procrastinate.RetryStrategy(
    max_attempts=2,
    exponential_wait=5,
    retry_exceptions={WeatherUnavailableError, psycopg.OperationalError},
)


def main() -> None:
    """Worker for `OPTIFUEL_WORKER_AIRLINE`: its queue, its model, nothing else."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    tenants = Tenants(settings.tenants)
    try:
        airline = tenants.authenticate(settings.worker_airline)
    except UnknownAirlineError as error:
        sys.exit(f"OPTIFUEL_WORKER_AIRLINE: {error}")
    if settings.weather_url is None or settings.weather_token is None:
        sys.exit("OPTIFUEL_WEATHER_URL and OPTIFUEL_WEATHER_TOKEN are required")
    version = tenants.model_version(airline)
    try:
        # Fail fast: without its own model the worker never starts, and jobs wait queued.
        model = FileModelRepository(settings.model_dir).load(airline, version)
    except (OSError, ValueError, ValidationError) as error:
        sys.exit(f"no usable model {version} for {airline}: {error}")

    url = settings.database_url.get_secret_value()
    # One connection: the worker runs one job at a time (Procrastinate's default concurrency).
    pool = ConnectionPool(
        url, min_size=1, max_size=1, open=False, check=ConnectionPool.check_connection
    )
    weather = HttpWeatherClient(
        str(settings.weather_url), settings.weather_token.get_secret_value(), httpx2.HTTPTransport()
    )
    service = FuelService(model, weather, PostgresResultRepository(pool), SystemClock())
    queue = queue_app(procrastinate.PsycopgConnector(conninfo=url))

    # Sync task: Procrastinate runs it in a thread, off the worker's event loop.
    @queue.task(name="fuel_estimate", pass_context=True, retry=RETRY)
    def fuel_estimate(context: procrastinate.JobContext, flight_plan: dict[str, Any]) -> None:
        job_id = context.job.id
        if job_id is None:
            raise ValueError("a claimed job always has an id")
        service.estimate(job_id, FlightPlan.model_validate(flight_plan))

    with pool:
        queue.run_worker(queues=[queue_name(airline)], name=f"worker-{airline}")


if __name__ == "__main__":
    main()
