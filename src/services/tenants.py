from collections.abc import Mapping

from src.config import Tenant


class UnknownAirlineError(Exception):
    """No airline named, or one that is not configured."""


class AircraftNotEnabledError(Exception):
    """The plan's aircraft type is not enabled for the airline."""


class Tenants:
    """Tenant registry: the configured airlines and what each may do. No default, no fallback.

    `authenticate` first; the other lookups take an airline it returned."""

    def __init__(self, tenants: Mapping[str, Tenant]) -> None:
        self._tenants = tenants

    def authenticate(self, airline: str | None) -> str:
        if airline is None or airline not in self._tenants:
            raise UnknownAirlineError(f"unknown airline: {airline!r}")
        return airline

    def codes(self) -> list[str]:
        return sorted(self._tenants)

    def check_aircraft(self, airline: str, aircraft_type: str) -> None:
        if aircraft_type not in self._tenants[airline].aircraft_types:
            raise AircraftNotEnabledError(f"aircraft type {aircraft_type!r} not enabled")

    def model_version(self, airline: str) -> str:
        return self._tenants[airline].model_version
