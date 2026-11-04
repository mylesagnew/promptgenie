# Deployment

PromptGenie is CLI-first (see [ROADMAP.md](../ROADMAP.md)). This document
covers the container image and the optional HTTP API adapter
(`promptgenie_service`) for teams that want to run generate and lint behind an
internal endpoint instead of shelling out to the CLI. `/v1/generate` can also
scan the prompt it generates; there is no standalone scan endpoint yet.

## Container image

The `Dockerfile` is a multi-stage build: a `builder` stage compiles wheels
for the package and its dependencies, and a `runtime` stage installs only
those wheels (no compiler, no source tree, non-root user).

By default the image is built with the `service` extra (FastAPI + uvicorn)
so the same image can run either mode:

```bash
# CLI mode (default CMD)
docker build -t promptgenie .
docker run --rm promptgenie promptgenie generate "add rate limiting to the login endpoint"

# API mode
docker run --rm -p 127.0.0.1:8080:8080 -e PROMPTGENIE_API_KEY promptgenie \
  python -m uvicorn promptgenie_service.api.main:app --host 0.0.0.0 --port 8080
```

To build a smaller CLI-only image without the API dependencies:

```bash
docker build --build-arg PROMPTGENIE_EXTRAS= -t promptgenie:cli .
```

## Local development stack

`docker-compose.yml` starts the API plus Postgres and Redis, with every
port bound to `127.0.0.1` because the credentials are development defaults:

```bash
export PROMPTGENIE_API_KEY="$(openssl rand -hex 32)"
docker compose up --build
curl http://localhost:8080/health/live
```

Postgres and Redis are not wired into the API yet — the current
`promptgenie_service` endpoints call `promptgenie.core` directly and hold no
external state. They're provisioned now so the run-history work described in
`ROADMAP.md`'s cloud-service track has a local target to develop against.
There is no object store in the stack yet; choose one when an endpoint needs it.

## HTTP API

Endpoints currently exposed by `promptgenie_service.api.main:app`:

| Method | Path            | Wraps                              |
|--------|-----------------|-------------------------------------|
| GET    | `/health/live`  | liveness — always 200 once the process is up |
| GET    | `/health/ready` | readiness — checks config loads cleanly |
| POST   | `/v1/generate`  | `promptgenie.core.generator.generate_prompt` (+ lint/scan) |
| POST   | `/v1/lint`      | `promptgenie.core.linter.lint` |

These wrap the same core functions the CLI uses — no business logic lives in
`promptgenie_service`, only request/response translation and input validation. Requests are
synchronous; there is no job queue yet, so callers should avoid feeding it
work that runs long (large context packs, high `--mode exhaustive` templates
against slow providers).

Config resolution follows the CLI convention: a `.promptgenie.yaml` is
looked up from the process's working directory (`PROMPTGENIE_CONFIG_PATH`
can override this) unless the request explicitly opts out.

### Authentication

`/v1` endpoints need `Authorization: Bearer <key>`, where the key is the value
of `PROMPTGENIE_API_KEY`. Without that variable they return 503, so a deployment
that forgets it is unusable rather than open. The health endpoints and FastAPI's
`/docs` and `/openapi.json` are not authenticated.

```bash
curl -X POST http://localhost:8080/v1/lint \
  -H "Authorization: Bearer $PROMPTGENIE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "do the thing"}'
```

This is one shared key with no per-caller identity, and there is no rate limiting
or TLS. Keep the API on a trusted network or behind a proxy that provides them.

## What's not here yet

Per the roadmap, the following are deliberately out of scope until later
phases: async job execution/worker, Postgres-backed run history, OIDC/JWT
auth, rate limiting, Kubernetes manifests, and Terraform. Don't wire the API
to Postgres or Redis speculatively — add that when a concrete endpoint
needs persisted state.
