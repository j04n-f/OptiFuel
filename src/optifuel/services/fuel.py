from collections.abc import Sequence
from datetime import datetime, timedelta
from itertools import pairwise
from math import asin, atan2, cos, degrees, exp, radians, sin, sqrt

from optifuel.clients.clock import Clock
from optifuel.clients.weather import WeatherClient, Wind, WindQuery
from optifuel.repositories.protocols import ResultRepository
from optifuel.schemas import FlightPlan, FuelModel, FuelResult, Waypoint

EARTH_RADIUS_KM = 6371.0
KMH_PER_KT = 1.852


class FuelEstimateError(Exception):
    """Permanent: the plan cannot be estimated, so retrying will not help."""


class FuelService:
    """Worker side of `fuel_estimate`, bound to one airline's model."""

    def __init__(
        self, model: FuelModel, weather: WeatherClient, results: ResultRepository, clock: Clock
    ) -> None:
        self._model = model
        self._weather = weather
        self._results = results
        self._clock = clock

    def estimate(self, job_id: int, plan: FlightPlan) -> None:
        """Record the result, or record the error and re-raise so the queue fails the job."""
        if plan.departure_time is None:
            raise ValueError("departure_time is set by JobService.submit before queueing")
        try:
            result = self._estimate(plan.waypoints, plan.departure_time)
        except FuelEstimateError as error:
            self._results.record_error(job_id, str(error), self._clock.now())
            raise
        self._results.record_success(job_id, result, self._clock.now())

    def _estimate(self, waypoints: Sequence[Waypoint], departure: datetime) -> FuelResult:
        # Before the weather call: extrapolating the model could underestimate fuel.
        if outside := outside_envelope(self._model, waypoints):
            raise FuelEstimateError(f"out_of_envelope: waypoints {', '.join(map(str, outside))}")
        queries = [
            WindQuery(w.latitude, w.longitude, w.altitude, eta)
            for w, eta in zip(waypoints, etas(waypoints, departure), strict=True)
        ]
        return integrate(self._model, waypoints, self._weather.winds(queries))


def outside_envelope(model: FuelModel, waypoints: Sequence[Waypoint]) -> list[int]:
    (v_min, v_max), (h_min, h_max) = model.envelope.speed_kmh, model.envelope.altitude_ft
    return [
        i
        for i, w in enumerate(waypoints)
        if not (v_min <= w.speed <= v_max and h_min <= w.altitude <= h_max)
    ]


def etas(waypoints: Sequence[Waypoint], departure: datetime) -> list[datetime]:
    # ponytail: still-air ETAs, so wind lookups are approximate. Iterate once with ground-speed
    # ETAs if forecast error matters.
    times = [departure]
    for a, b in pairwise(waypoints):
        times.append(times[-1] + timedelta(hours=distance_km(a, b) / a.speed))
    return times


def integrate(model: FuelModel, waypoints: Sequence[Waypoint], winds: Sequence[Wind]) -> FuelResult:
    """Sum of fuel flow * segment time; segment i flies at waypoint i's airspeed, altitude, wind."""
    fuel = distance = duration = 0.0
    # The last waypoint's wind has no segment after it; strict catches a short weather reply.
    for i, ((a, b), wind) in enumerate(zip(pairwise(waypoints), winds[:-1], strict=True)):
        d = distance_km(a, b)
        headwind = KMH_PER_KT * wind.speed_kt * cos(radians(wind.from_deg - bearing_deg(a, b)))
        ground_speed = a.speed - headwind
        if ground_speed <= 0:
            raise FuelEstimateError(f"non_positive_ground_speed: waypoint {i}")
        hours = d / ground_speed
        fuel += fuel_flow(model, a) * hours
        distance += d
        duration += hours
    return FuelResult(
        total_fuel_lb=fuel, distance_km=distance, duration_h=duration, model_version=model.version
    )


def fuel_flow(model: FuelModel, w: Waypoint) -> float:
    c = model.coefficients
    return exp(c.ln_c) * w.speed**c.speed * w.altitude**c.altitude


def distance_km(a: Waypoint, b: Waypoint) -> float:
    lat_a, lat_b = radians(a.latitude), radians(b.latitude)
    h = (
        sin((lat_b - lat_a) / 2) ** 2
        + cos(lat_a) * cos(lat_b) * sin(radians(b.longitude - a.longitude) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * asin(sqrt(h))


def bearing_deg(a: Waypoint, b: Waypoint) -> float:
    """Initial great-circle bearing from a to b, degrees clockwise from north."""
    lat_a, lat_b = radians(a.latitude), radians(b.latitude)
    d_lon = radians(b.longitude - a.longitude)
    y = sin(d_lon) * cos(lat_b)
    x = cos(lat_a) * sin(lat_b) - sin(lat_a) * cos(lat_b) * cos(d_lon)
    return degrees(atan2(y, x))
