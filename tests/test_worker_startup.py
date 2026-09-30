from pathlib import Path

import pytest
from pydantic import SecretStr

from src.config import Settings
from src.worker import Worker, WorkerStartupError, build
from tests.conftest import ABC_MODEL, TENANTS, XYZ_MODEL


def settings(model_dir: Path, **overrides: object) -> Settings:
    fields: dict[str, object] = {
        "database_url": SecretStr("postgresql://unused"),
        "tenants": TENANTS,
        "worker_airline": "ABC",
        "model_dir": model_dir,
        "weather_url": "http://weather.test",
        "weather_token": SecretStr("token"),
        **overrides,
    }
    return Settings.model_validate(fields)


def mount(model_dir: Path, airline: str, contents: str) -> None:
    (model_dir / airline).mkdir()
    (model_dir / airline / "2026-09-30.json").write_text(contents)


def test_builds_worker_for_its_airline_without_connecting(tmp_path: Path) -> None:
    mount(tmp_path, "ABC", ABC_MODEL.model_dump_json())

    worker = build(settings(tmp_path))

    assert isinstance(worker, Worker)
    assert worker.airline == "ABC"


@pytest.mark.parametrize(
    ("overrides", "mounted", "reason"),
    [
        pytest.param({"worker_airline": None}, None, "OPTIFUEL_WORKER_AIRLINE", id="no airline"),
        pytest.param({"worker_airline": "QQQ"}, None, "unknown airline", id="unknown airline"),
        pytest.param({"weather_url": None}, None, "OPTIFUEL_WEATHER_URL", id="no weather"),
        pytest.param({}, None, "no usable model", id="model missing"),
        pytest.param({}, "{not json", "no usable model", id="model unreadable"),
        pytest.param({}, XYZ_MODEL.model_dump_json(), "holds XYZ", id="another airline's model"),
    ],
)
def test_refuses_to_start_without_its_own_model(
    tmp_path: Path, overrides: dict[str, object], mounted: str | None, reason: str
) -> None:
    if mounted is not None:
        mount(tmp_path, "ABC", mounted)

    with pytest.raises(WorkerStartupError, match=reason):
        build(settings(tmp_path, **overrides))
