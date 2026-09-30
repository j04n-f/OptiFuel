from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status

from src.services.jobs import JobQueue
from src.services.tenants import Tenants, UnknownAirlineError


# Providers read what api.create_app put on app.state; tests swap them via dependency_overrides.
def get_tenants(request: Request) -> Tenants:
    return request.app.state.tenants


def get_job_queue(request: Request) -> JobQueue:
    return request.app.state.jobs


JobQueueDep = Annotated[JobQueue, Depends(get_job_queue)]


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
