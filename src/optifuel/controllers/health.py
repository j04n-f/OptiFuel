from typing import Annotated

from fastapi import APIRouter, Depends

from optifuel.config import Settings
from optifuel.controllers.deps import get_settings

router = APIRouter()


@router.get("/health")
def health(_settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    # Liveness only: settings unused, kept so the route goes through the composed app.
    return {"status": "ok"}
