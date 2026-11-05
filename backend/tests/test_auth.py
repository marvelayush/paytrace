from datetime import datetime, timedelta, timezone

import jwt

from app.config import get_settings
from tests.conftest import TEST_PASSWORD, login

COOKIE = get_settings().cookie_name


def test_login_sets_httponly_session_cookie(client, finance_user):
    response = login(client, finance_user.email)

    assert response.status_code == 200
    assert response.json() == {
        "id": finance_user.id,
        "email": "finance@paytrace.demo",
        "name": "Finance Exec",
        "role": "finance_exec",
    }
    set_cookie = response.headers["set-cookie"]
    assert set_cookie.startswith(f"{COOKIE}=")
    assert "HttpOnly" in set_cookie
    assert "samesite=lax" in set_cookie.lower()
    # The password hash is never sent back.
    assert "password" not in response.text


def test_login_email_is_case_insensitive(client, finance_user):
    assert login(client, "FINANCE@PayTrace.Demo").status_code == 200


def test_wrong_password_and_unknown_email_give_the_same_answer(client, finance_user):
    wrong_password = login(client, finance_user.email, "not-the-password")
    unknown_email = login(client, "nobody@paytrace.demo", TEST_PASSWORD)

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json() == {"detail": "Email or password is incorrect."}
    assert "set-cookie" not in wrong_password.headers


def test_login_rejects_malformed_email(client):
    assert client.post("/auth/login", json={"email": "not-an-email", "password": "x"}).status_code == 422


def test_me_returns_the_signed_in_user(finance_client):
    response = finance_client.get("/auth/me")
    assert response.status_code == 200
    assert response.json()["role"] == "finance_exec"


def test_me_without_session_is_401(client):
    assert client.get("/auth/me").status_code == 401


def test_tampered_token_is_rejected(client, finance_user):
    forged = jwt.encode({"sub": str(finance_user.id), "role": "finance_exec"}, "a-different-secret" * 3, "HS256")
    client.cookies.set(COOKIE, forged)
    assert client.get("/auth/me").status_code == 401


def test_expired_token_is_rejected(client, finance_user):
    settings = get_settings()
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    expired = jwt.encode({"sub": str(finance_user.id), "exp": past}, settings.jwt_secret, settings.jwt_algorithm)
    client.cookies.set(COOKIE, expired)
    assert client.get("/auth/me").status_code == 401


def test_role_is_read_from_database_not_token(client, db, founder_user):
    """A token claiming finance_exec for a co-founder account must not grant finance rights."""
    settings = get_settings()
    lying_token = jwt.encode(
        {"sub": str(founder_user.id), "role": "finance_exec", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        settings.jwt_secret,
        settings.jwt_algorithm,
    )
    client.cookies.set(COOKIE, lying_token)
    assert client.get("/auth/me").json()["role"] == "cofounder"


def test_logout_clears_the_cookie(finance_client):
    response = finance_client.post("/auth/logout")
    assert response.status_code == 204
    assert f'{COOKIE}=""' in response.headers["set-cookie"] or "Max-Age=0" in response.headers["set-cookie"]
    assert finance_client.get("/auth/me").status_code == 401


def test_login_is_rate_limited_after_repeated_failures(client, finance_user):
    max_attempts = get_settings().login_max_attempts
    for _ in range(max_attempts):
        assert login(client, finance_user.email, "wrong").status_code == 401

    blocked = login(client, finance_user.email, TEST_PASSWORD)
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0


def test_successful_login_resets_the_failure_count(client, finance_user):
    max_attempts = get_settings().login_max_attempts
    for _ in range(max_attempts - 1):
        login(client, finance_user.email, "wrong")
    assert login(client, finance_user.email).status_code == 200
    for _ in range(max_attempts - 1):
        assert login(client, finance_user.email, "wrong").status_code == 401


def _request_from(socket_host: str, forwarded_for: str | None):
    from starlette.requests import Request

    headers = [(b"x-forwarded-for", forwarded_for.encode())] if forwarded_for else []
    return Request({"type": "http", "headers": headers, "client": (socket_host, 1234)})


def test_client_ip_behind_trusted_proxies():
    from app.routers.auth import client_ip

    # Vercel proxy + Render: the client is two entries from the right; a forged left entry is ignored.
    request = _request_from("10.0.0.1", "6.6.6.6, 203.0.113.7, 76.76.21.1")
    assert client_ip(request, 2) == "203.0.113.7"
    assert client_ip(request, 1) == "76.76.21.1"
    # No trusted proxies, or fewer entries than expected: the socket address.
    assert client_ip(request, 0) == "10.0.0.1"
    assert client_ip(_request_from("10.0.0.1", None), 2) == "10.0.0.1"
