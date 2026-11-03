from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import (
    check_dummy_password,
    create_session_token,
    current_user,
    login_limiter,
    verify_password,
)
from app.config import get_settings
from app.db import get_db
from app.models import User
from app.schemas.auth import LoginRequest, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

WRONG_CREDENTIALS = "Email or password is incorrect."


def _limiter_key(request: Request, email: str) -> str:
    client_ip = request.client.host if request.client else "unknown"
    return f"{client_ip}|{email.lower()}"


@router.post("/login", response_model=UserOut)
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> User:
    key = _limiter_key(request, body.email)
    wait_seconds = login_limiter.seconds_until_allowed(key)
    if wait_seconds:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many attempts. Try again in {wait_seconds} seconds.",
            headers={"Retry-After": str(wait_seconds)},
        )

    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None:
        check_dummy_password(body.password)
        login_limiter.record_failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=WRONG_CREDENTIALS)
    if not verify_password(body.password, user.password_hash):
        login_limiter.record_failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=WRONG_CREDENTIALS)

    login_limiter.reset(key)
    settings = get_settings()
    response.set_cookie(
        key=settings.cookie_name,
        value=create_session_token(user),
        max_age=settings.jwt_expire_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,  # type: ignore[arg-type]
        path="/",
    )
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.cookie_name,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,  # type: ignore[arg-type]
    )


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> User:
    return user
