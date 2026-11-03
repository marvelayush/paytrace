"""The co-founder role is read-only (A2). These tests enforce that on every write endpoint.

The sweep reads every route registered through `app.main.API_ROUTERS`, so an endpoint added in a
later milestone without the finance-exec guard fails here automatically. A second test compares
the sweep against the public OpenAPI schema, so a route registered some other way cannot slip past.
"""

import re

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.auth import FINANCE_EXEC, require_finance_exec
from app.main import API_ROUTERS, WRITE_ROUTES_OPEN_TO_ALL_ROLES
from app.models import User
from tests.conftest import login

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _guard_roles(dependant) -> tuple[str, ...] | None:
    """Find a `require_role(...)` guard anywhere in a route's dependency tree."""
    for sub_dependant in dependant.dependencies:
        roles = getattr(sub_dependant.call, "allowed_roles", None)
        if roles is not None:
            return roles
        nested = _guard_roles(sub_dependant)
        if nested is not None:
            return nested
    return None


def _api_routes(app: FastAPI, routers: list[APIRouter]) -> list[APIRoute]:
    """Routes declared directly on the app plus every route of the given routers."""
    direct = [route for route in app.routes if isinstance(route, APIRoute)]
    from_routers = [route for router in routers for route in router.routes if isinstance(route, APIRoute)]
    return direct + from_routers


def _write_routes(routes: list[APIRoute]) -> list[tuple[str, APIRoute]]:
    return [
        (method, route)
        for route in routes
        for method in sorted(route.methods & WRITE_METHODS)
        if (method, route.path) not in WRITE_ROUTES_OPEN_TO_ALL_ROLES
    ]


def _unguarded(routes: list[APIRoute]) -> list[str]:
    return [
        f"{method} {route.path}"
        for method, route in _write_routes(routes)
        if _guard_roles(route.dependant) != (FINANCE_EXEC,)
    ]


def _fill_path_params(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


# ---------- the real application ----------

def test_sweep_sees_every_route_in_the_openapi_schema(app):
    swept = {(method, route.path) for route in _api_routes(app, API_ROUTERS) for method in route.methods}
    documented = {
        (method.upper(), path) for path, operations in app.openapi()["paths"].items() for method in operations
    }
    assert documented <= swept, f"Routes the sweep cannot see: {documented - swept}"
    # Sanity check that the sweep is not vacuous.
    assert ("POST", "/auth/login") in swept


def test_every_write_route_is_guarded(app):
    assert _unguarded(_api_routes(app, API_ROUTERS)) == []


def test_cofounder_gets_403_on_every_write_route(founder_client, app):
    for method, route in _write_routes(_api_routes(app, API_ROUTERS)):
        response = founder_client.request(method, _fill_path_params(route.path), json={})
        assert response.status_code == 403, f"{method} {route.path} returned {response.status_code}"


def test_anonymous_gets_401_on_every_write_route(client, app):
    for method, route in _write_routes(_api_routes(app, API_ROUTERS)):
        response = client.request(method, _fill_path_params(route.path), json={})
        assert response.status_code == 401, f"{method} {route.path} returned {response.status_code}"


# ---------- the guard itself ----------
# Milestone 1 has no data-changing endpoints yet, so a probe route proves the guard end to end.

@pytest.fixture
def probe_router() -> APIRouter:
    probe = APIRouter()

    @probe.post("/__probe/write")
    def probe_write(user: User = Depends(require_finance_exec)) -> dict[str, str]:
        return {"written_by": user.role}

    return probe


@pytest.fixture
def probe_app(app, probe_router):
    app.include_router(probe_router)
    return app


def test_guard_allows_finance_exec(probe_app, finance_user):
    finance = TestClient(probe_app)
    login(finance, finance_user.email)
    response = finance.post("/__probe/write")
    assert response.status_code == 200
    assert response.json() == {"written_by": "finance_exec"}


def test_guard_blocks_cofounder_with_403(probe_app, founder_user):
    founder = TestClient(probe_app)
    login(founder, founder_user.email)
    response = founder.post("/__probe/write")
    assert response.status_code == 403
    assert response.json() == {"detail": "Your role cannot perform this action."}


def test_guard_blocks_anonymous_with_401(probe_app):
    assert TestClient(probe_app).post("/__probe/write").status_code == 401


def test_sweep_accepts_guarded_and_flags_unguarded_routes(app, probe_router):
    """Self-test: the sweep must pass a guarded route and catch one that forgot the guard."""
    leaky_router = APIRouter()

    @leaky_router.post("/__probe/leaky")
    def leaky_write() -> None:
        return None

    routes = _api_routes(app, [*API_ROUTERS, probe_router, leaky_router])
    assert _unguarded(routes) == ["POST /__probe/leaky"]
