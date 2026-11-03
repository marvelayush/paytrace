"""Seed the database with demo data.

Milestone 1: creates the two demo users. Partners, rate cards, sample files and a first
reconciliation run are added in Milestone 3.

Passwords come from DEMO_FINANCE_PASSWORD and DEMO_FOUNDER_PASSWORD (never hard-coded).
Safe to run more than once: existing users keep their id, and their name, role and password are updated.

Usage (from the repository root):
    backend/.venv/Scripts/python scripts/seed.py     # Windows
    backend/.venv/bin/python scripts/seed.py         # macOS / Linux
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
os.chdir(REPO_ROOT / "backend")  # so the app finds ../.env

from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env(REPO_ROOT / ".env")

from sqlalchemy import select  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import User  # noqa: E402

DEMO_USERS = [
    ("finance@paytrace.demo", "Priya (Finance)", "finance_exec", "DEMO_FINANCE_PASSWORD"),
    ("founder@paytrace.demo", "Arjun (Co-founder)", "cofounder", "DEMO_FOUNDER_PASSWORD"),
]


def seed_users() -> None:
    with SessionLocal() as db:
        for email, name, role, password_env in DEMO_USERS:
            password = os.environ.get(password_env)
            if not password:
                raise SystemExit(f"Set {password_env} before seeding.")
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(email=email)
                db.add(user)
            user.name = name
            user.role = role
            user.password_hash = hash_password(password)
            print(f"  user {email} ({role})")
        db.commit()


if __name__ == "__main__":
    print("Seeding demo users...")
    seed_users()
    print("Done.")
