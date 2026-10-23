import logging
import time

from prometheus_client import Counter, Gauge, Histogram
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("app.requests")

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "route", "status_code"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency in seconds", ["method", "route"]
)
REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress", "HTTP requests currently being processed", ["method"]
)
APP_INFO = Gauge("app_info", "Build information", ["version", "commit", "environment"])

# Probe and scrape traffic is constant noise; it is still counted but logged at DEBUG.
QUIET_ROUTES = {"/health", "/ready", "/metrics"}


def route_label(scope: Scope) -> str:
    """The route *template* (e.g. /api/v1/items/{item_id}), never the raw path.

    Labelling by raw path creates a new time series for every ID ever requested,
    which eventually exhausts memory. Unmatched paths (404s) share one label.
    """
    route = scope.get("route")
    return getattr(route, "path", None) or "unmatched"


class MetricsMiddleware:
    """Pure ASGI middleware: records Prometheus metrics and logs one line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        status_code = 500  # if the app raises before responding, it's a server error

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        start = time.perf_counter()
        REQUESTS_IN_PROGRESS.labels(method).inc()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start
            REQUESTS_IN_PROGRESS.labels(method).dec()
            route = route_label(scope)
            REQUEST_COUNT.labels(method, route, str(status_code)).inc()
            REQUEST_LATENCY.labels(method, route).observe(duration)
            logger.log(
                logging.DEBUG if route in QUIET_ROUTES else logging.INFO,
                "%s %s %s",
                method,
                scope["path"],
                status_code,
                extra={
                    "http_method": method,
                    "route": route,
                    "path": scope["path"],
                    "status_code": status_code,
                    "duration_ms": round(duration * 1000, 2),
                },
            )
