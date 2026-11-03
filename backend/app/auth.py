"""Password hashing, session tokens and role checks.

The session is a signed JWT stored in an httpOnly cookie, so browser JavaScript can never read it.
Every protected endpoint depends on `current_user`; endpoints that change data also depend on
`require_role("finance_exec")`, because the co-founder role is read-only (A2).
"""

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User

FINANCE_EXEC = "finance_exec"
COFOUNDER = "cofounder"


# ---------- passwords ----------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


# A real hash of a random value, checked when the email is unknown so a login
# takes the same time whether or not the account exists (no user enumeration).
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


def check_dummy_password(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


# ---------- session tokens ----------

def create_session_token(user: User) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def read_session_token(token: str) -> int | None:
    """Return the user id inside a valid token, or None if the token is missing, expired or tampered with."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


# ---------- dependencies ----------

def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(get_settings().cookie_name)
    user_id = read_session_token(token) if token else None
    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Please sign in.")
    return user


def require_role(*allowed_roles: str) -> Callable[..., User]:
    """Dependency factory: allow the request only if the signed-in user has one of `allowed_roles`.

    The role is always read from the database, not from the token, so a role change applies at once.
    """

    def check_role(user: User = Depends(current_user)) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Your role cannot perform this action.")
        return user

    # Marker read by the access-control test that sweeps every write route.
    check_role.allowed_roles = allowed_roles  # type: ignore[attr-defined]
    return check_role


# Shorthand used by every endpoint that changes data.
require_finance_exec = require_role(FINANCE_EXEC)


# ---------- login rate limiting (A14) ----------

class LoginRateLimiter:
    """Counts failed logins per key in a sliding time window. In memory: fine for one backend instance."""

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _drop_old(self, key: str, now: float) -> deque[float]:
        attempts = self._failures[key]
        while attempts and now - attempts[0] > self.window_seconds:
            attempts.popleft()
        return attempts

    def seconds_until_allowed(self, key: str) -> int:
        """0 if the key may try again now, otherwise how many seconds to wait."""
        now = time.monotonic()
        with self._lock:
            attempts = self._drop_old(key, now)
            if len(attempts) < self.max_attempts:
                return 0
            return max(1, int(self.window_seconds - (now - attempts[0])) + 1)

    def record_failure(self, key: str) -> None:
        with self._lock:
            self._failures[key].append(time.monotonic())

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._failures.clear()
            else:
                self._failures.pop(key, None)


login_limiter = LoginRateLimiter(
    max_attempts=get_settings().login_max_attempts,
    window_seconds=get_settings().login_window_seconds,
)
