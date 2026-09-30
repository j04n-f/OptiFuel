from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from optifuel.config import Settings
from optifuel.controllers.deps import JobServiceDep, get_settings

router = APIRouter()


@router.get("/health")
def health(_settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    # Liveness only: settings unused, kept so the route goes through the composed app.
    return {"status": "ok"}


@router.get("/ready")
def ready(service: JobServiceDep) -> dict[str, str]:
    if not service.ready():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "database unavailable")
    return {"status": "ready"}
