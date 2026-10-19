FROM python:3.14-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml ./


FROM builder AS mcp-builder

RUN uv sync --no-dev --no-install-project --extra mcp


FROM builder AS auth-gate-builder

RUN uv sync --no-dev --no-install-project --extra auth-gate


FROM builder AS socket-proxy-builder

RUN uv sync --no-dev --no-install-project --extra socket-proxy


FROM python:3.14-slim AS socket-proxy

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH" \
    TZ=UTC

WORKDIR /app

COPY --from=socket-proxy-builder /opt/venv /opt/venv
COPY config/__init__.py config/constants.py ./config/
COPY domain/__init__.py domain/generation.py ./domain/
COPY infrastructure/__init__.py ./infrastructure/
COPY infrastructure/docker/__init__.py infrastructure/docker/constants.py infrastructure/docker/socket_proxy.py ./infrastructure/docker/
COPY utils/__init__.py utils/logger.py ./utils/
RUN python -c "import infrastructure.docker.socket_proxy"

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:2375/_ping', timeout=3).status == 200 else 1)"

ENTRYPOINT ["python", "-m", "infrastructure.docker.socket_proxy"]


FROM python:3.14-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH" \
    TZ=UTC

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN mkdir -p /app/logs

ENTRYPOINT ["/usr/bin/tini", "--"]


FROM runtime AS auth-gate

COPY --from=auth-gate-builder /opt/venv /opt/venv

COPY auth_gate/ ./auth_gate/
COPY config/__init__.py config/constants.py config/settings.py ./config/
COPY infrastructure/__init__.py ./infrastructure/
COPY infrastructure/http/ ./infrastructure/http/
COPY utils/__init__.py utils/logger.py ./utils/
RUN python -c "import auth_gate.main"

RUN groupadd --system --gid 10001 auth-gate \
    && useradd --system --uid 10001 --gid auth-gate --no-create-home --shell /usr/sbin/nologin auth-gate \
    && chown auth-gate:auth-gate /app/logs

USER 10001:10001

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8081/healthz', timeout=3).status == 200 else 1)"

CMD ["python", "-m", "auth_gate.main"]


FROM runtime AS mcp

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        fd-find \
        ripgrep \
    && ln -s "$(command -v fdfind)" /usr/local/bin/fd \
    && rm -rf /var/lib/apt/lists/*

COPY --from=mcp-builder /opt/venv /opt/venv

COPY config/__init__.py config/constants.py config/settings.py ./config/
COPY domain/ ./domain/
COPY infrastructure/__init__.py ./infrastructure/
COPY infrastructure/docker/__init__.py infrastructure/docker/constants.py infrastructure/docker/sandbox_client.py ./infrastructure/docker/
COPY infrastructure/fs/ ./infrastructure/fs/
COPY infrastructure/http/ ./infrastructure/http/
COPY mcp_server/ ./mcp_server/
COPY sandbox_scripts/ ./sandbox_scripts/
COPY services/ ./services/
COPY utils/ ./utils/
COPY main.py ./
RUN python -c "import main"

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=3).status == 200 else 1)"

CMD ["python", "main.py"]