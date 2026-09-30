from fastapi import FastAPI

from optifuel.clients.clock import SystemClock
from optifuel.config import Settings
from optifuel.controllers import health, jobs, tenants


def create_app(settings: Settings) -> FastAPI:
    """Composition root. Controllers read what it puts on `app.state` via `controllers/deps.py`."""
    app = FastAPI(title="OptiFuel")
    app.state.settings = settings
    app.state.clock = SystemClock()
    # ponytail: no real JobRepository yet, so /v1/jobs answers 500 outside tests. The Postgres
    # repository (Procrastinate defer + job_records) lands as `app.state.jobs` here.
    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(tenants.router)
    return app


# ponytail: env is read at import. Once Settings gains required fields, add a zero-arg
# factory building `Settings()` and run uvicorn with `--factory`, so tests can import this.
app = create_app(Settings())
