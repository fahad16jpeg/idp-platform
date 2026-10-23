import os

# Tests must never export telemetry to a real Application Insights resource.
os.environ.pop("APPLICATIONINSIGHTS_CONNECTION_STRING", None)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.routers.items import store  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as test_client:  # `with` runs the lifespan startup/shutdown
        yield test_client


@pytest.fixture(autouse=True)
def empty_store():
    store.clear()
    yield
    store.clear()
