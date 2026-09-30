import json

import httpx2
import pytest

from src.clients.weather import HttpWeatherClient, Wind, WindQuery
from tests.conftest import DEPARTURE

ROUTE = [WindQuery(0, 0, 5000, DEPARTURE), WindQuery(1, 0.5, 4000, DEPARTURE.replace(hour=11))]


def test_asks_weather_api_for_whole_route_in_one_call() -> None:
    requests: list[httpx2.Request] = []

    def weather_api(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        winds = [{"speed_kt": 10, "from_deg": 270}, {"speed_kt": 25.5, "from_deg": 90}]
        return httpx2.Response(200, json={"winds": winds})

    client = HttpWeatherClient("http://weather.test", "s3cret", httpx2.MockTransport(weather_api))

    winds = client.winds(ROUTE)

    assert winds == [Wind(speed_kt=10, from_deg=270), Wind(speed_kt=25.5, from_deg=90)]
    [request] = requests
    assert (request.method, str(request.url)) == ("POST", "http://weather.test/winds")
    assert request.headers["Authorization"] == "Bearer s3cret"
    assert json.loads(request.content) == {
        "points": [
            {"latitude": 0, "longitude": 0, "altitude_ft": 5000, "eta": "2026-09-30T10:00:00Z"},
            {"latitude": 1, "longitude": 0.5, "altitude_ft": 4000, "eta": "2026-09-30T11:00:00Z"},
        ]
    }


def test_raises_when_weather_api_fails() -> None:
    transport = httpx2.MockTransport(lambda _: httpx2.Response(503))
    client = HttpWeatherClient("http://weather.test", "s3cret", transport)

    with pytest.raises(httpx2.HTTPStatusError, match="503"):
        client.winds(ROUTE)
