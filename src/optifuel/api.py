from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import procrastinate
from fastapi import FastAPI
from psycopg_pool import ConnectionPool

from optifuel.clients.clock import SystemClock
from optifuel.config import Settings
from optifuel.controllers import health, jobs, tenants
from optifuel.repositories.postgres import PostgresJobRepository, queue_app


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
    app.state.settings = settings
    app.state.clock = SystemClock()
    app.state.jobs = PostgresJobRepository(pool, queue)
    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(tenants.router)
    return app


def from_env() -> FastAPI:
    """`uvicorn --factory optifuel.api:from_env`: reads the environment at startup, not import."""
    return create_app(Settings())
