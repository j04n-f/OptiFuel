from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import procrastinate
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from psycopg_pool import ConnectionPool

from src.clients.clock import SystemClock
from src.config import Settings
from src.controllers import health, jobs, tenants
from src.repositories.postgres import PostgresJobStore
from src.services.jobs import JobQueue, queue_app
from src.services.tenants import Tenants


def create_app(settings: Settings) -> FastAPI:
    """Composition root. Controllers read what it puts on `app.state` via `controllers/deps.py`."""
    # min_size=0 connects on first use: the API starts and answers /health with Postgres down,
    # while /ready reports it. `check` replaces connections that died with a Postgres restart.
    pool = ConnectionPool(
        settings.database_url.get_secret_value(),
        min_size=0,
        max_size=10,
        open=False,
        check=ConnectionPool.check_connection,
    )

    queue = queue_app(procrastinate.SyncPsycopgConnector())

    registry = Tenants(settings.tenants)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        pool.open()
        queue.open(pool)
        try:
            yield
        finally:
            queue.close()
            pool.close()

    app = FastAPI(title="OptiFuel", lifespan=lifespan)

    app.state.tenants = registry
    app.state.jobs = JobQueue(PostgresJobStore(pool, queue), SystemClock(), registry)

    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(tenants.router)

    # Mounted last: routes match in order, so the catch-all "/" never shadows the API.
    app.mount("/", StaticFiles(packages=[("src", "static")], html=True))

    return app


def from_env() -> FastAPI:
    """`uvicorn --factory src.api:from_env`: reads the environment at startup, not import."""
    return create_app(Settings())
