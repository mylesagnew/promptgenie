# syntax=docker/dockerfile:1.7
#
# Multi-stage build. Two runtime modes share the same image (the entrypoint
# is tini, not `promptgenie`, so CMD can be replaced wholesale):
#   CLI (default): docker run promptgenie promptgenie generate "..."
#   API:            docker run promptgenie python -m uvicorn promptgenie_service.api.main:app --host 0.0.0.0 --port 8080
#
# To update the pinned digest: docker pull python:3.12-slim && docker inspect
# python:3.12-slim --format='{{index .RepoDigests 0}}'
ARG PYTHON_IMAGE=python:3.12-slim@sha256:c2d8472b831337ab296a8ce652e1ba786e9e3034fc445dc58b50a7f5251f0003
# Set to "" to build a CLI-only image without FastAPI/uvicorn.
ARG PROMPTGENIE_EXTRAS=service

FROM ${PYTHON_IMAGE} AS builder
ARG PROMPTGENIE_EXTRAS

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY pyproject.toml README.md ./
COPY promptgenie ./promptgenie
COPY promptgenie_service ./promptgenie_service

# Build wheels for the package *and* all of its (extras) dependencies, so the
# runtime stage can install fully offline from /dist with --no-index.
RUN pip install --upgrade pip \
 && pip wheel --wheel-dir /dist ".${PROMPTGENIE_EXTRAS:+[$PROMPTGENIE_EXTRAS]}"


FROM ${PYTHON_IMAGE} AS runtime
ARG PROMPTGENIE_EXTRAS

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app

# Non-root user + tini (PID 1 signal forwarding / zombie reaping)
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 1001 promptgenie \
 && useradd --uid 1001 --gid promptgenie --no-create-home --shell /sbin/nologin promptgenie

COPY --from=builder /dist /dist

# Install from the prebuilt wheels only — no network access, no source tree.
RUN pip install --no-cache-dir --no-index --find-links=/dist \
      "promptgenie${PROMPTGENIE_EXTRAS:+[$PROMPTGENIE_EXTRAS]}" \
 && rm -rf /dist

USER promptgenie

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["promptgenie", "--version"]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["promptgenie", "--help"]
