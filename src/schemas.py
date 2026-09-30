from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)


class Waypoint(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)  # json.loads accepts Infinity; gt=0 lets it by

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    speed: float = Field(gt=0, description="True airspeed, km/h")
    altitude: float = Field(gt=0, description="Altitude, ft")


NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
# One form per instant, so the same plan sent with another UTC offset hashes to one plan_key.
UtcDatetime = Annotated[AwareDatetime, AfterValidator(lambda t: t.astimezone(UTC))]


class FlightPlan(BaseModel):
    airline: NonEmpty
    aircraft_type: NonEmpty
    registration: NonEmpty
    flight_id: int
    departure_time: UtcDatetime | None = Field(
        default=None, description="Defaults to the time the job is received"
    )
    waypoints: list[Waypoint] = Field(min_length=2)


class JobSubmission(BaseModel):
    type: Literal["fuel_estimate"]
    payload: FlightPlan


class FuelResult(BaseModel):
    total_fuel_lb: float
    distance_km: float
    duration_h: float
    model_version: str


class JobView(BaseModel):
    id: int
    type: str
    airline: str
    flight_id: int
    status: Literal["queued", "running", "succeeded", "failed"]
    attempts: int
    submitted_at: datetime
    finished_at: datetime | None = None
    result: FuelResult | None = None
    error: str | None = None


class PowerLawCoefficients(BaseModel):
    ln_c: float
    speed: float
    altitude: float


class Envelope(BaseModel):
    speed_kmh: tuple[float, float]
    altitude_ft: tuple[float, float]


class FuelModel(BaseModel):
    """Model file: `ff = e^ln_c · v^speed · h^altitude` (lb/h), valid only inside `envelope`."""

    airline: str
    version: str
    form: Literal["power_law"]
    coefficients: PowerLawCoefficients
    envelope: Envelope
