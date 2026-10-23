# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=__PYTHON_VERSION__

# ---- builder: install dependencies into an isolated virtualenv --------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt .
RUN pip install -r requirements.txt

# ---- runtime: only the venv and the app code, running as a non-root user ----
FROM python:${PYTHON_VERSION}-slim AS runtime

ARG GIT_SHA=local
ARG APP_VERSION=0.1.0

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_COMMIT=${GIT_SHA} \
    APP_VERSION=${APP_VERSION}

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
# Code stays owned by root: the app user can read it but not modify it.
COPY app ./app

USER 10001:10001

EXPOSE 8000

# Uses Python instead of curl so no extra packages are needed in the image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

# --proxy-headers: Azure Container Apps terminates TLS in front of the app.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
