from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from src.controllers.deps import AirlineDep, JobServiceDep
from src.schemas import JobSubmission, JobView
from src.services.jobs import AircraftNotEnabledError, AirlineMismatchError

router = APIRouter(prefix="/v1/jobs")


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def submit_job(
    submission: JobSubmission, airline: AirlineDep, service: JobServiceDep
) -> dict[str, int]:
    try:
        return {"id": service.submit(airline, submission)}
    except AirlineMismatchError as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(error)) from error
    except AircraftNotEnabledError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error


@router.get("")
def list_jobs(
    airline: AirlineDep, service: JobServiceDep, limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> list[JobView]:
    return service.recent(airline, limit)


@router.get("/{job_id}")
def get_job(job_id: int, airline: AirlineDep, service: JobServiceDep) -> JobView:
    job = service.get(airline, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return job
