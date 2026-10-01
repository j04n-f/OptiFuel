from typing import Annotated

from fastapi import APIRouter, Depends

from src.controllers.deps import get_tenants
from src.services.tenants import Tenants

router = APIRouter(prefix="/v1/tenants")


# Limitation: exists only because auth is mocked, so the page can pick an identity. Removed with
# real auth, where the token names the airline.
@router.get("")
def list_tenants(tenants: Annotated[Tenants, Depends(get_tenants)]) -> list[str]:
    return tenants.codes()
