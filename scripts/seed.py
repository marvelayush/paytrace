"""Seed the database with demo data.

Creates the two demo users, partners, sources, starting rate cards and a version-1 column
mapping for every source. `--reset` empties every table first, for a clean demo.

Passwords come from DEMO_FINANCE_PASSWORD and DEMO_FOUNDER_PASSWORD (never hard-coded).
Safe to run more than once: existing users keep their id, and their name, role and password are updated.

Usage (from the repository root):
    backend/.venv/Scripts/python scripts/seed.py [--reset]    # Windows
    backend/.venv/bin/python scripts/seed.py [--reset]        # macOS / Linux
"""

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
os.chdir(REPO_ROOT / "backend")  # so the app finds ../.env

from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env(REPO_ROOT / ".env")

from sqlalchemy import select, text  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.services.seeding import seed_initial_mappings, seed_reference_data  # noqa: E402

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


def reset_database() -> None:
    table_names = ", ".join(table.name for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))


def seed_partners_rate_cards_and_mappings() -> None:
    with SessionLocal() as db:
        partners = seed_reference_data(db)
        finance_id = db.scalar(select(User.id).where(User.email == DEMO_USERS[0][0]))
        mappings = seed_initial_mappings(db, created_by=finance_id)
        db.commit()
        print(f"  {len(partners)} partners with sources and rate cards; {mappings} column mappings added")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed PayTrace demo data.")
    parser.add_argument("--reset", action="store_true", help="empty every table first")
    args = parser.parse_args()

    if args.reset:
        print("Emptying all tables...")
        reset_database()
    print("Seeding demo users...")
    seed_users()
    print("Seeding partners, rate cards and column mappings...")
    seed_partners_rate_cards_and_mappings()
    print("Done.")


if __name__ == "__main__":
    main()
