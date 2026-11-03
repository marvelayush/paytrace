from fastapi import APIRouter, FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db import engine
from app.routers import auth, rate_cards

# Every feature router. Listed here (not only passed to include_router) so the access-control
# test can inspect each route's dependencies directly.
API_ROUTERS: list[APIRouter] = [auth.router, rate_cards.router]

# Routes that change data but are deliberately open to every role (or to no one signed in).
# The access-control test fails if any other write route lacks the finance-exec guard.
WRITE_ROUTES_OPEN_TO_ALL_ROLES = {("POST", "/auth/login"), ("POST", "/auth/logout")}


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="PayTrace API", version="0.1.0")

    # Only the frontend may call the API with cookies.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health", tags=["health"])
    def health(response: Response) -> dict[str, str]:
        """Liveness plus a database round trip, used by Render's health check."""
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "degraded", "database": "unreachable"}
        return {"status": "ok", "database": "ok"}

    for router in API_ROUTERS:
        app.include_router(router)
    return app


app = create_app()
