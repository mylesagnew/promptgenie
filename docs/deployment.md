# Deployment

PromptGenie is CLI-first (see [ROADMAP.md](../ROADMAP.md)). This document
covers the container image and the optional HTTP API adapter
(`promptgenie_service`) for teams that want to run generate/lint/scan behind
an internal endpoint instead of shelling out to the CLI.

## Container image

The `Dockerfile` is a multi-stage build: a `builder` stage compiles wheels
for the package and its dependencies, and a `runtime` stage installs only
those wheels (no compiler, no source tree, non-root user).

By default the image is built with the `service` extra (FastAPI + uvicorn)
so the same image can run either mode:

```bash
# CLI mode (default CMD)
docker build -t promptgenie .
docker run --rm promptgenie generate "add rate limiting to the login endpoint"

# API mode
docker run --rm -p 8080:8080 promptgenie \
  python -m uvicorn promptgenie_service.api.main:app --host 0.0.0.0 --port 8080
```

To build a smaller CLI-only image without the API dependencies:

```bash
docker build --build-arg PROMPTGENIE_EXTRAS= -t promptgenie:cli .
```

## Local development stack

`docker-compose.yml` starts the API plus Postgres, Redis, and MinIO:

```bash
docker compose up --build
curl http://localhost:8080/health/live
```

Postgres/Redis/MinIO are not wired into the API yet — the current
`promptgenie_service` endpoints call `promptgenie.core` directly and hold no
external state. They're provisioned now so the run-history/object-storage
work described in `ROADMAP.md`'s cloud-service track has a local target to
develop against.

## HTTP API

Endpoints currently exposed by `promptgenie_service.api.main:app`:

| Method | Path            | Wraps                              |
|--------|-----------------|-------------------------------------|
| GET    | `/health/live`  | liveness — always 200 once the process is up |
| GET    | `/health/ready` | readiness — checks config loads cleanly |
| POST   | `/v1/generate`  | `promptgenie.core.generator.generate_prompt` (+ lint/scan) |
| POST   | `/v1/lint`      | `promptgenie.core.linter.lint` |

These wrap the same core functions the CLI uses — no business logic lives in
`promptgenie_service`, only request/response translation. Requests are
synchronous; there is no job queue yet, so callers should avoid feeding it
work that runs long (large context packs, high `--mode exhaustive` templates
against slow providers).

Config resolution follows the CLI convention: a `.promptgenie.yaml` is
looked up from the process's working directory (`PROMPTGENIE_CONFIG_PATH`
can override this) unless the request explicitly opts out.

## What's not here yet

Per the roadmap, the following are deliberately out of scope until later
phases: async job execution/worker, Postgres-backed run history, OIDC/JWT
auth, rate limiting, Kubernetes manifests, and Terraform. Don't wire the API
to Postgres/Redis/MinIO speculatively — add that when a concrete endpoint
needs persisted state.
