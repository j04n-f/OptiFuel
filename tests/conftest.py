from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from optifuel.api import create_app
from optifuel.config import Settings


@pytest.fixture
def app() -> FastAPI:
    return create_app(Settings(environment="dev"))


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client
