import logging
import os

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def configure_telemetry(app: FastAPI) -> bool:
    """Send requests, dependencies, exceptions and logs to Application Insights.

    Only active when APPLICATIONINSIGHTS_CONNECTION_STRING is set (Terraform injects it
    into the Container App), so local runs and tests never try to reach Azure.
    """
    if not os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        logger.info("Application Insights not configured; telemetry export disabled")
        return False

    # Imported lazily: these packages are only needed when telemetry is enabled.
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    configure_azure_monitor()
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health,ready,metrics")
    logger.info("Application Insights telemetry enabled")
    return True
