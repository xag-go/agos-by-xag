# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm
# Same uid as the earlier gateway (node, 1000), so an existing data volume keeps working.
RUN useradd --uid 1000 --no-create-home --shell /usr/sbin/nologin agos \
 && mkdir -p /data /internal && chown agos:agos /data /internal
WORKDIR /app
COPY --from=build /app /app
# AGOS_CORE_HOST: the container's own private network (outside a container the core
# listens on 127.0.0.1); every route still needs the internal token.
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    AGOS_DATA_DIR=/data AGOS_INTERNAL_TOKEN_FILE=/internal/token AGOS_CORE_HOST=0.0.0.0
USER agos
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"]
CMD ["python", "-m", "agos_core"]
