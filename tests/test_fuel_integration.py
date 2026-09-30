import pytest

from src.clients.weather import Wind
from src.schemas import Waypoint
from src.services.fuel import integrate
from tests.conftest import ABC_MODEL

NORTHBOUND = [
    Waypoint(latitude=0, longitude=0, speed=200, altitude=5000),
    Waypoint(latitude=1, longitude=0, speed=200, altitude=5000),
]


def test_headwind_raises_fuel_over_calm_air() -> None:
    calm = [Wind(speed_kt=0, from_deg=0)] * 2
    headwind = [Wind(speed_kt=20, from_deg=0)] * 2

    still = integrate(ABC_MODEL, NORTHBOUND, calm)
    against = integrate(ABC_MODEL, NORTHBOUND, headwind)

    # Ground speed drops from 200 to 200 - 20 kt * 1.852 = 162.96 km/h over the same distance.
    assert against.total_fuel_lb == pytest.approx(still.total_fuel_lb * 200 / 162.96)
    assert against.distance_km == still.distance_km
