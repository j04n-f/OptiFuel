import logging
import sys
from dataclasses import dataclass

import httpx2
import procrastinate
from psycopg_pool import ConnectionPool
from pydantic import ValidationError

from src.clients.clock import SystemClock
from src.clients.weather import HttpWeatherClient
from src.config import Settings
from src.repositories.files import FileModelRepository
from src.repositories.postgres import PostgresJobStore
from src.services.fuel import FuelService
from src.services.jobs import queue_app, queue_name, register_fuel_estimate
from src.services.tenants import Tenants, UnknownAirlineError


class WorkerStartupError(Exception):
    """The worker cannot serve its airline. It refuses to start; jobs wait queued."""


@dataclass(frozen=True)
class Worker:
    airline: str
    app: procrastinate.App
    pool: ConnectionPool

    def run(self) -> None:
        with self.pool:
            self.app.run_worker(queues=[queue_name(self.airline)], name=f"worker-{self.airline}")


def build(settings: Settings) -> Worker:
    """Worker for `OPTIFUEL_WORKER_AIRLINE`: its queue, its model, nothing else. Opens nothing."""
    tenants = Tenants(settings.tenants)
    try:
        airline = tenants.authenticate(settings.worker_airline)
    except UnknownAirlineError as error:
        raise WorkerStartupError(f"OPTIFUEL_WORKER_AIRLINE: {error}") from error
    if settings.weather_url is None or settings.weather_token is None:
        raise WorkerStartupError("OPTIFUEL_WEATHER_URL and OPTIFUEL_WEATHER_TOKEN are required")
    version = tenants.model_version(airline)
    try:
        # Fail fast: without its own model the worker never starts, and jobs wait queued.
        model = FileModelRepository(settings.model_dir).load(airline, version)
    except (OSError, ValueError, ValidationError) as error:
        raise WorkerStartupError(f"no usable model {version} for {airline}: {error}") from error

    url = settings.database_url.get_secret_value()
    # One connection: the worker runs one job at a time (Procrastinate's default concurrency).
    pool = ConnectionPool(
        url, min_size=1, max_size=1, open=False, check=ConnectionPool.check_connection
    )
    app = queue_app(procrastinate.PsycopgConnector(conninfo=url))
    weather = HttpWeatherClient(
        str(settings.weather_url), settings.weather_token.get_secret_value(), httpx2.HTTPTransport()
    )
    register_fuel_estimate(
        app, FuelService(model, weather, PostgresJobStore(pool, app), SystemClock())
    )
    return Worker(airline, app, pool)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        worker = build(Settings())
    except WorkerStartupError as error:
        sys.exit(str(error))
    worker.run()


if __name__ == "__main__":
    main()
