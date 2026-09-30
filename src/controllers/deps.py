from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from src.clients.clock import Clock
from src.repositories.protocols import JobRepository
from src.services.jobs import JobService
from src.services.tenants import Tenants, UnknownAirlineError


# Providers read what api.create_app put on app.state; tests swap them via dependency_overrides.
def get_tenants(request: Request) -> Tenants:
    return request.app.state.tenants


def get_clock(request: Request) -> Clock:
    return request.app.state.clock


def get_job_repository(request: Request) -> JobRepository:
    return request.app.state.jobs


def get_job_service(
    jobs: Annotated[JobRepository, Depends(get_job_repository)],
    clock: Annotated[Clock, Depends(get_clock)],
    tenants: Annotated[Tenants, Depends(get_tenants)],
) -> JobService:
    return JobService(jobs, clock, tenants)


JobServiceDep = Annotated[JobService, Depends(get_job_service)]


def current_airline(
    tenants: Annotated[Tenants, Depends(get_tenants)],
    x_airline: Annotated[str | None, Header()] = None,
) -> str:
    # ponytail: mocked identity (D9), the header is trusted. Real auth replaces only this
    # dependency, returning the airline claim of a token verified at the gateway.
    try:
        return tenants.authenticate(x_airline)
    except UnknownAirlineError as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(error)) from error


AirlineDep = Annotated[str, Depends(current_airline)]
