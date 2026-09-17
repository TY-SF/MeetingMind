from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


ACCESS_TOKEN = "phase-seven-access-token-1234567890"


def protected_app(tmp_path: Path, monkeypatch):
    env_file = tmp_path / "protected.env"
    env_file.write_text(
        f"MEETINGMIND_API_TOKEN={ACCESS_TOKEN}\n"
        "FRONTEND_ORIGIN=http://localhost:5173\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(env_file))
    monkeypatch.delenv("MEETINGMIND_API_TOKEN", raising=False)
    return create_app(tmp_path / "runtime")


def test_access_token_protects_business_api_but_not_health(tmp_path: Path, monkeypatch) -> None:
    app = protected_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/health/ready").status_code == 200

        status = client.get("/api/v1/auth/status").json()
        assert status == {"required": True, "authenticated": False, "storage": "session"}

        missing = client.get("/api/v1/meetings", headers={"X-Request-ID": "auth-missing"})
        assert missing.status_code == 401
        assert missing.json()["detail"]["code"] == "ACCESS_TOKEN_REQUIRED"
        assert missing.headers["www-authenticate"] == "Bearer"
        assert missing.headers["x-request-id"] == "auth-missing"

        invalid = client.get("/api/v1/meetings", headers={"Authorization": "Bearer wrong-token"})
        assert invalid.status_code == 401
        assert invalid.json()["detail"]["code"] == "ACCESS_TOKEN_INVALID"

        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}
        assert client.get("/api/v1/meetings", headers=headers).status_code == 200
        assert client.get("/api/v1/auth/status", headers=headers).json()["authenticated"] is True


def test_access_token_is_exposed_as_openapi_bearer_scheme(tmp_path: Path, monkeypatch) -> None:
    spec = protected_app(tmp_path, monkeypatch).openapi()

    assert spec["components"]["securitySchemes"]["BearerAuth"]["scheme"] == "bearer"
    assert spec["paths"]["/api/v1/meetings"]["get"]["security"] == [{"BearerAuth": []}]
    assert "security" not in spec["paths"]["/api/v1/health"]["get"]
    assert "security" not in spec["paths"]["/api/v1/auth/status"]["get"]


def test_access_token_must_be_strong_enough(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / "weak.env"
    env_file.write_text("MEETINGMIND_API_TOKEN=too-short\n", encoding="utf-8")
    monkeypatch.setenv("MEETINGMIND_ENV_FILE", str(env_file))
    monkeypatch.delenv("MEETINGMIND_API_TOKEN", raising=False)

    with pytest.raises(ValueError, match="至少需要 32 个字符"):
        Settings.from_env(base_dir=tmp_path)


def test_cors_preflight_allows_authorization_header(tmp_path: Path, monkeypatch) -> None:
    app = protected_app(tmp_path, monkeypatch)
    with TestClient(app) as client:
        response = client.options(
            "/api/v1/meetings",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )

    assert response.status_code == 200
    assert "Authorization" in response.headers["access-control-allow-headers"]
