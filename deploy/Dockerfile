# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

RUN uv sync --locked --no-dev


FROM python:3.12-slim-bookworm

RUN groupadd --system radar && useradd --system --gid radar radar

COPY --from=builder /app /app
WORKDIR /data

ENV PATH="/app/.venv/bin:$PATH" \
    RADAR_HOST=0.0.0.0 \
    RADAR_PORT=8765

USER radar
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=4).status == 200 else 1)"]

CMD ["sh", "-c", "radar init --root /data >/dev/null 2>&1 || true; exec radar serve --root /data --host ${RADAR_HOST} --port ${RADAR_PORT}"]
