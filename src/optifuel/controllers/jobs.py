from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from optifuel.controllers.deps import get_job_service
from optifuel.schemas import JobSubmission, JobView
from optifuel.services.jobs import JobService

router = APIRouter(prefix="/v1/jobs")

JobServiceDep = Annotated[JobService, Depends(get_job_service)]


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def submit_job(submission: JobSubmission, service: JobServiceDep) -> dict[str, int]:
    return {"id": service.submit(submission)}


@router.get("/{job_id}")
def get_job(job_id: int, service: JobServiceDep) -> JobView:
    job = service.get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "job not found")
    return job
