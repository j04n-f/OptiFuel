from fastapi import APIRouter, HTTPException, status

from src.controllers.deps import JobServiceDep

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def ready(service: JobServiceDep) -> dict[str, str]:
    if not service.ready():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable")
    return {"status": "ready"}
