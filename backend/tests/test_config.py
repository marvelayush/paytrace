"""Deployment-facing settings and headers."""

import pytest

from app.config import Settings

SECRET = "x" * 40


@pytest.mark.parametrize(
    ("given", "used"),
    [
        ("postgres://u:p@host/db?sslmode=require", "postgresql+psycopg://u:p@host/db?sslmode=require"),
        ("postgresql://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ],
)
def test_hosted_database_urls_get_the_psycopg_driver(given, used):
    assert Settings(jwt_secret=SECRET, database_url=given).database_url == used


def test_several_frontend_origins_are_allowed():
    settings = Settings(jwt_secret=SECRET, frontend_origin="https://paytrace.vercel.app/, https://preview.vercel.app")
    assert settings.frontend_origins == ["https://paytrace.vercel.app", "https://preview.vercel.app"]


def test_short_jwt_secret_is_refused():
    with pytest.raises(ValueError):
        Settings(jwt_secret="too-short")


def test_responses_carry_security_headers(client):
    response = client.get("/health")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"


def test_cors_allows_only_the_frontend(client):
    allowed = client.options("/auth/me", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"})
    blocked = client.options("/auth/me", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-origin" not in blocked.headers
