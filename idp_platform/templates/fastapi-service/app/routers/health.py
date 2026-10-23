import logging
import platform
import time
from collections.abc import Callable

from fastapi import APIRouter, Response, status

from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ops"])

START_TIME = time.monotonic()

# Readiness checks: name -> function returning True when the dependency is usable.
# Register one per external dependency (database, cache, downstream API...).
_readiness_checks: dict[str, Callable[[], bool]] = {}


def register_readiness_check(name: str, check: Callable[[], bool]) -> None:
    _readiness_checks[name] = check


def unregister_readiness_check(name: str) -> None:
    _readiness_checks.pop(name, None)


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up. Keep this free of dependency checks, otherwise a
    database outage makes the platform restart healthy containers in a loop."""
    return {"status": "ok"}


@router.get("/ready")
def ready(response: Response) -> dict[str, object]:
    """Readiness: dependencies are reachable, so this replica may receive traffic."""
    results: dict[str, bool] = {}
    for name, check in _readiness_checks.items():
        try:
            results[name] = bool(check())
        except Exception:
            logger.exception("readiness check failed", extra={"check": name})
            results[name] = False

    is_ready = all(results.values())
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if is_ready else "not_ready", "checks": results}


@router.get("/info")
def info() -> dict[str, object]:
    settings = get_settings()
    return {
        "name": settings.name,
        "version": settings.version,
        "commit": settings.commit,
        "environment": settings.environment,
        "python": platform.python_version(),
        "uptime_seconds": round(time.monotonic() - START_TIME, 2),
    }
