from typing import Annotated

from fastapi import APIRouter, Depends

from optifuel.config import Settings
from optifuel.controllers.deps import get_settings

router = APIRouter(prefix="/v1/tenants")


# ponytail: exists only because auth is mocked, so the page can pick an identity. Removed with
# real auth, where the token names the airline.
@router.get("")
def list_tenants(settings: Annotated[Settings, Depends(get_settings)]) -> list[str]:
    return sorted(settings.tenants)
