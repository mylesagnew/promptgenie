"""Tests for the promptgenie_service FastAPI adapter.

These exercise the HTTP layer only — the underlying generate/lint/scan
behavior is covered by tests/test_generator.py etc. Every request passes
no_config=True so results don't depend on a .promptgenie.yaml that might
exist above the test run's cwd.
"""

from fastapi.testclient import TestClient

from promptgenie_service.api.main import app

client = TestClient(app)


def test_health_live():
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_ready():
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_generate_happy_path():
    resp = client.post(
        "/v1/generate",
        json={"task": "add rate limiting to the login endpoint", "no_config": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["prompt"]
    assert body["target"]
    assert body["template"]
    assert isinstance(body["token_estimate"], int)
    assert "total" in body["score"]
    assert body["lint"] is not None and "score" in body["lint"]
    assert body["scan"] is not None and "risk_level" in body["scan"]


def test_generate_can_skip_lint_and_scan():
    resp = client.post(
        "/v1/generate",
        json={
            "task": "add rate limiting to the login endpoint",
            "no_config": True,
            "include_lint": False,
            "include_scan": False,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["lint"] is None
    assert body["scan"] is None


def test_generate_unknown_template_is_422():
    resp = client.post(
        "/v1/generate",
        json={"task": "do something", "template": "no-such-template", "no_config": True},
    )
    assert resp.status_code == 422
    assert "no-such-template" in resp.json()["detail"]


def test_generate_unknown_template_best_effort_falls_back():
    resp = client.post(
        "/v1/generate",
        json={
            "task": "do something",
            "template": "no-such-template",
            "no_config": True,
            "best_effort": True,
        },
    )
    assert resp.status_code == 200


def test_generate_missing_task_is_422():
    resp = client.post("/v1/generate", json={"no_config": True})
    assert resp.status_code == 422


def test_lint_happy_path():
    resp = client.post(
        "/v1/lint",
        json={"prompt": "do the thing", "no_config": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["score"], int)
    assert any(issue["code"] == "TASK_003" for issue in body["issues"])


def test_lint_missing_prompt_is_422():
    resp = client.post("/v1/lint", json={"no_config": True})
    assert resp.status_code == 422
