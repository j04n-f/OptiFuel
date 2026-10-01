from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx2
from pydantic import BaseModel, TypeAdapter


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


class WeatherUnavailableError(Exception):
    """Transient: timeout, connection error or 5xx. The job is retried with backoff."""


class WeatherClient(Protocol):
    def winds(self, points: Sequence[WindQuery]) -> list[Wind]:
        """One wind per point, in order: a single batched call for the whole route. Raises
        `WeatherUnavailableError` when a retry may succeed; any other error is permanent."""
        ...


_POINTS = TypeAdapter(list[WindQuery])


class _WindsReply(BaseModel):
    winds: list[Wind]


class HttpWeatherClient:
    """`POST {url}/winds` with a bearer token. Raises on timeout, connection error or non-2xx,
    so the job records why it failed; 4xx stays permanent, since a retry would ask the same.
    `transport` is the network edge: tests hand in a fake."""

    def __init__(self, url: str, token: str, transport: httpx2.BaseTransport) -> None:
        self._http = httpx2.Client(
            base_url=url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
            transport=transport,
        )

    def winds(self, points: Sequence[WindQuery]) -> list[Wind]:
        body = {"points": _POINTS.dump_python(list(points), mode="json")}

        try:
            response = self._http.post("/winds", json=body)
        except httpx2.TransportError as error:
            raise WeatherUnavailableError(f"weather API unreachable: {error}") from error

        if response.is_server_error:
            raise WeatherUnavailableError(f"weather API answered {response.status_code}")

        response.raise_for_status()

        return _WindsReply.model_validate_json(response.content).winds
