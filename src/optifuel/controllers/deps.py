from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from optifuel.clients.clock import Clock
from optifuel.config import Settings
from optifuel.repositories.protocols import JobRepository
from optifuel.services.jobs import JobService, UnknownAirlineError


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
    settings: Annotated[Settings, Depends(get_settings)],
) -> JobService:
    return JobService(jobs, clock, settings.tenants)


JobServiceDep = Annotated[JobService, Depends(get_job_service)]


def current_airline(
    service: JobServiceDep, x_airline: Annotated[str | None, Header()] = None
) -> str:
    # ponytail: mocked identity (D9), the header is trusted. Real auth replaces only this
    # dependency, returning the airline claim of a token verified at the gateway.
    try:
        return service.authenticate(x_airline)
    except UnknownAirlineError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error


AirlineDep = Annotated[str, Depends(current_airline)]
