from fastapi import APIRouter, FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db import engine
from app.routers import auth, claims, dashboard, rate_cards, recon, sources, uploads

# Every feature router. Listed here (not only passed to include_router) so the access-control
# test can inspect each route's dependencies directly.
API_ROUTERS: list[APIRouter] = [auth.router, rate_cards.router, sources.router, uploads.router, recon.router, claims.router, dashboard.router]

# Routes that change data but are deliberately open to every role (or to no one signed in).
# The access-control test fails if any other write route lacks the finance-exec guard.
WRITE_ROUTES_OPEN_TO_ALL_ROLES = {("POST", "/auth/login"), ("POST", "/auth/logout")}


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",  # financial data: never cached by browsers or proxies
}


def create_app() -> FastAPI:
    settings = get_settings()
    docs = "/docs" if settings.enable_docs else None
    app = FastAPI(title="PayTrace API", version="1.0.0", docs_url=docs, redoc_url=None, openapi_url="/openapi.json" if docs else None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    # Only the frontend may call the API with cookies.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition"],  # file downloads read their name from it
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
