from typing import Annotated

from fastapi import Depends, Request

from optifuel.clients.clock import Clock
from optifuel.config import Settings
from optifuel.repositories.protocols import JobRepository
from optifuel.services.jobs import JobService


# Providers read what api.create_app put on app.state; tests swap them via dependency_overrides.
def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def get_job_repository(request: Request) -> JobRepository:
    return request.app.state.jobs


def get_job_service(
    jobs: Annotated[JobRepository, Depends(get_job_repository)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> JobService:
    return JobService(jobs, clock)
