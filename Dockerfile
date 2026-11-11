# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv UV_SYSTEM_CERTS=true
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY certs/ /tmp/build-certs/
RUN cp /tmp/build-certs/*.crt /usr/local/share/ca-certificates/ 2>/dev/null || true \
    && rm -rf /tmp/build-certs \
    && update-ca-certificates
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-install-project --no-dev

FROM python:3.12-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    DOCULENS_ENVIRONMENT=production DOCULENS_LOG_LEVEL=INFO \
    HF_HOME=/models/huggingface \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
WORKDIR /app
# PyMuPDF and FAISS native wheels link against the system C++ runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libstdc++6 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /usr/local/share/ca-certificates/ /usr/local/share/ca-certificates/
RUN update-ca-certificates
RUN groupadd --system --gid 10001 doculens \
    && useradd --system --uid 10001 --gid doculens --home-dir /nonexistent --shell /usr/sbin/nologin doculens \
    && mkdir -p /models/huggingface && chown -R 10001:10001 /models
COPY --from=builder --chown=10001:10001 /opt/venv /opt/venv
COPY --chown=10001:10001 app/ ./app/
COPY --chown=10001:10001 frontend/ ./frontend/
COPY pyproject.toml ./pyproject.toml
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()"]
# Sessions are process-local: run exactly one application worker.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
