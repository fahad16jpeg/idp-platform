import json
import logging

from app.logging_config import JsonFormatter


def test_metrics_endpoint_exposes_prometheus_format(client):
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "http_requests_total" in response.text
    assert "app_info" in response.text


def test_metrics_label_by_route_template_not_raw_path(client):
    item_id = client.post("/api/v1/items", json={"name": "x"}).json()["id"]
    client.get(f"/api/v1/items/{item_id}")

    text = client.get("/metrics").text
    assert 'route="/api/v1/items/{item_id}"' in text
    assert item_id not in text  # one series per route, not one per ID


def test_unknown_paths_share_one_label(client):
    assert client.get("/does-not-exist").status_code == 404
    text = client.get("/metrics").text
    assert 'route="unmatched",status_code="404"' in text
    assert "does-not-exist" not in text


def test_json_log_format_includes_extra_fields():
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    record.route = "/health"
    payload = json.loads(JsonFormatter().format(record))
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["route"] == "/health"
