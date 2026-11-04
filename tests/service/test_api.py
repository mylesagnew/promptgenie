"""Tests for the promptgenie_service FastAPI adapter.

These exercise the HTTP layer only — the underlying generate/lint/scan
behavior is covered by tests/test_generator.py etc. Every request passes
no_config=True so results don't depend on a .promptgenie.yaml that might
exist above the test run's cwd.
"""

import pytest
from fastapi.testclient import TestClient

from promptgenie_service.api.main import app

API_KEY = "test-key"

client = TestClient(app, headers={"Authorization": f"Bearer {API_KEY}"})
anonymous = TestClient(app)


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("PROMPTGENIE_API_KEY", API_KEY)


@pytest.mark.parametrize("path", ["/v1/generate", "/v1/lint"])
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-key"},
        {"Authorization": f"Basic {API_KEY}"},
    ],
)
def test_v1_rejects_bad_credentials(path, headers):
    resp = anonymous.post(path, json={}, headers=headers)
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("configured", [None, ""])
@pytest.mark.parametrize("path", ["/v1/generate", "/v1/lint"])
def test_v1_fails_closed_without_configured_key(monkeypatch, path, configured):
    if configured is None:
        monkeypatch.delenv("PROMPTGENIE_API_KEY")
    else:
        monkeypatch.setenv("PROMPTGENIE_API_KEY", configured)
    resp = client.post(path, json={})
    assert resp.status_code == 503


def test_health_does_not_need_a_key():
    assert anonymous.get("/health/live").status_code == 200
    assert anonymous.get("/health/ready").status_code == 200


def test_health_ready_hides_config_error_detail(monkeypatch):
    monkeypatch.setenv("PROMPTGENIE_CONFIG_PATH", "/no/such/dir/promptgenie.yaml")
    resp = anonymous.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json() == {"detail": "config not ready"}


@pytest.mark.parametrize("target", ["../../etc/profile", "..\\evil", "a/b", ".hidden", ""])
def test_generate_rejects_path_like_target(target):
    resp = client.post(
        "/v1/generate", json={"task": "do something", "target": target, "no_config": True}
    )
    assert resp.status_code == 422


def test_generate_accepts_named_target():
    resp = client.post(
        "/v1/generate", json={"task": "do something", "target": "claude-code", "no_config": True}
    )
    assert resp.status_code == 200
    assert resp.json()["target"] == "claude-code"


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
