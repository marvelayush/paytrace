"""Test setup: a dedicated Postgres database, migrated with Alembic, emptied between tests."""

import os

# Point the app at the test database BEFORE any app module is imported.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://paytrace:paytrace@localhost:5432/paytrace_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("JWT_SECRET", "test-only-secret-not-used-anywhere-else-0123456789")
# Uploaded files go to a throwaway folder; the AI is never called from tests.
import tempfile  # noqa: E402

os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="paytrace-test-uploads-")
os.environ["GEMINI_API_KEY"] = ""

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.auth import hash_password, login_limiter  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base, User  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_PASSWORD = "correct-horse-battery"


def _create_test_database_if_missing() -> None:
    url = make_url(TEST_DATABASE_URL)
    admin_engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        exists = connection.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": url.database})
        if not exists:
            connection.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin_engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    """Build the schema with the real migrations, so the migrations themselves are tested too."""
    _create_test_database_if_missing()
    config = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    config.attributes["database_url"] = TEST_DATABASE_URL
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables() -> Iterator[None]:
    yield
    table_names = ", ".join(table.name for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
    login_limiter.reset()


@pytest.fixture
def db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def make_user(db: Session, email: str, role: str, name: str = "Test User") -> User:
    user = User(email=email, password_hash=hash_password(TEST_PASSWORD), name=name, role=role)
    db.add(user)
    db.commit()
    return user


@pytest.fixture
def finance_user(db: Session) -> User:
    return make_user(db, "finance@paytrace.demo", "finance_exec", "Finance Exec")


@pytest.fixture
def founder_user(db: Session) -> User:
    return make_user(db, "founder@paytrace.demo", "cofounder", "Co Founder")


def login(client: TestClient, email: str, password: str = TEST_PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


@pytest.fixture
def finance_client(app, finance_user: User) -> TestClient:
    client = TestClient(app)
    assert login(client, finance_user.email).status_code == 200
    return client


@pytest.fixture
def founder_client(app, founder_user: User) -> TestClient:
    client = TestClient(app)
    assert login(client, founder_user.email).status_code == 200
    return client
