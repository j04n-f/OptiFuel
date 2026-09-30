from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class WindQuery:
    latitude: float
    longitude: float
    altitude_ft: float
    eta: datetime


@dataclass(frozen=True)
class Wind:
    speed_kt: float
    from_deg: float


class WeatherClient(Protocol):
    def winds(self, points: Sequence[WindQuery]) -> list[Wind]:
        """One wind per point, in order: a single batched call for the whole route."""
        ...
