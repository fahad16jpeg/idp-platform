from app.routers.health import register_readiness_check, unregister_readiness_check


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_with_no_checks(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


def test_ready_returns_503_when_a_check_fails(client):
    register_readiness_check("database", lambda: False)
    try:
        response = client.get("/ready")
    finally:
        unregister_readiness_check("database")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"database": False}}


def test_ready_treats_check_exceptions_as_failures(client):
    def broken() -> bool:
        raise ConnectionError("cannot reach dependency")

    register_readiness_check("cache", broken)
    try:
        response = client.get("/ready")
    finally:
        unregister_readiness_check("cache")
    assert response.status_code == 503
    assert response.json()["checks"] == {"cache": False}


def test_info(client):
    body = client.get("/info").json()
    assert body["name"] == "__PROJECT_NAME__"
    assert {"version", "commit", "environment", "python", "uptime_seconds"} <= body.keys()
