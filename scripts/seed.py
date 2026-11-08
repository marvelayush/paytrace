"""Seed the database with demo data.

Creates the two demo users, partners, sources, starting rate cards and a version-1 column
mapping for every source, then processes every sample report in sample_data/ through the real
upload pipeline, runs one full reconciliation and opens claims, so the app is never empty on first login.
It also adds a few returns marked in the last few days (so the returns tracker always shows some still inside
the receipt window) and suggests orders for partner lines that arrived without an order ID (review queue).

`--reset` empties every table first, for a clean demo. `--no-data` stops after the reference data.

Passwords come from DEMO_FINANCE_PASSWORD and DEMO_FOUNDER_PASSWORD (never hard-coded).
Safe to run more than once: existing users keep their id, and their name, role and password are updated;
sample lines already loaded are recognised as duplicates and not stored twice.

Usage (from the repository root):
    backend/.venv/Scripts/python scripts/seed.py [--reset]    # Windows
    backend/.venv/bin/python scripts/seed.py [--reset]        # macOS / Linux
"""

import argparse
import os
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
os.chdir(REPO_ROOT / "backend")  # so the app finds ../.env

from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env(REPO_ROOT / ".env")

from sqlalchemy import select, text  # noqa: E402

from app.auth import hash_password  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.models import Base, ColumnMapping, Partner, Source, User  # noqa: E402
from app.sample_data.formats import FORMATS, format_for, write_file  # noqa: E402
from app.sample_data.generator import generate  # noqa: E402
from app.services.claims import refresh_claims  # noqa: E402
from app.services.match_ai import get_ranker  # noqa: E402
from app.services.matching import run_reconciliation, today_in_india  # noqa: E402
from app.services.review_queue import queue_counts, refresh_suggestions  # noqa: E402
from app.services.seeding import seed_initial_mappings, seed_reference_data  # noqa: E402
from app.services.upload_processing import process_file  # noqa: E402

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


def load_sample_files() -> None:
    sample_dir = REPO_ROOT / "sample_data"
    with SessionLocal() as db:
        finance_id = db.scalar(select(User.id).where(User.email == DEMO_USERS[0][0]))
        # Orders first, then every partner report (the order is cosmetic: matching runs at the end).
        for layout in sorted(FORMATS, key=lambda item: item.file_kind != "orders"):
            source = db.scalar(
                select(Source)
                .join(Partner, Partner.id == Source.partner_id)
                .where(Partner.name == layout.partner, Source.file_kind == layout.file_kind)
            )
            mapping = db.scalar(select(ColumnMapping).where(ColumnMapping.source_id == source.id, ColumnMapping.is_active))
            upload = process_file(db, source, mapping, sample_dir / layout.filename, layout.filename, finance_id)
            print(f"  {layout.filename:<34} {upload.status:<6} {upload.rows_ok:>6} rows  {upload.duration_ms:>5} ms")
        load_recent_returns(db, finance_id)
        summary = run_reconciliation(db, started_by=finance_id, return_window_days=get_settings().return_receipt_days)
        claim_changes = refresh_claims(db)
        db.commit()
        print(f"  reconciled {summary.order_count:,} orders in {summary.duration_ms} ms: {summary.status_counts}")
        print(f"  money at risk Rs {summary.money_at_risk_paise / 100:,.2f}; auto-matched {summary.auto_matched_pct}%")
        print(f"  claims: {claim_changes['claims_opened']} opened with {claim_changes['added']} orders")
        suggest_orders_for_unmatched_lines(db)


def _process(db, partner: str, file_kind: str, path: Path, user_id: int | None):
    source = db.scalar(
        select(Source).join(Partner, Partner.id == Source.partner_id).where(Partner.name == partner, Source.file_kind == file_kind)
    )
    mapping = db.scalar(select(ColumnMapping).where(ColumnMapping.source_id == source.id, ColumnMapping.is_active))
    return process_file(db, source, mapping, path, path.name, user_id)


def load_recent_returns(db, finance_id: int | None) -> None:
    """Website returns marked in the last few days, with no warehouse scan yet: the tracker's "waiting" state.

    The sample month is fixed in time, so without these every return would look either received or overdue.
    They go through the real pipeline as a small orders file and the couriers' freight invoices.
    """
    today = today_in_india()
    window = get_settings().return_receipt_days
    data = generate(n_orders=600, seed=int(today.strftime("%Y%m%d")), start=today - timedelta(days=16), days=8,
                    include_brief_samples=False, number_offset=500_000)
    leaked = {order_id for order_id, _, _ in data.injected}
    recent = [order for order in data.orders if order["channel"] == "Website" and order["order_id"] not in leaked
              and order["returned_date"] is not None and today - timedelta(days=window - 1) <= order["returned_date"] <= today]
    ids = {order["order_id"] for order in recent}
    freight = [line for line in data.freight_lines if line["order_id"] in ids]
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder)
        files = [("Website", "orders", recent)] + [
            (courier, "freight_invoice", [line for line in freight if line["courier"] == courier]) for courier in ("Courier A", "Courier B")
        ]
        for partner, file_kind, records in files:
            if not records:
                continue
            layout = format_for(partner, file_kind)
            path = write_file(layout, records, out)
            renamed = path.with_name(f"recent_returns_{path.name}")
            path.rename(renamed)
            upload = _process(db, partner, file_kind, renamed, finance_id)
            print(f"  {renamed.name:<34} {upload.status:<6} {upload.rows_ok:>6} rows  {upload.duration_ms:>5} ms")
    print(f"  {len(recent)} recent returns still inside the {window}-day receipt window")


def suggest_orders_for_unmatched_lines(db) -> None:
    """Rule shortlist plus AI ranking (when GEMINI_API_KEY is set) for every line without an order ID."""
    settings = get_settings()
    ranker = get_ranker(settings.gemini_api_key, settings.gemini_model, settings.gemini_thinking_level or None)
    lines = refresh_suggestions(db, ranker=ranker)
    db.commit()
    counts = queue_counts(db)
    print(f"  review queue: {lines} lines without an order ID, {counts['high_confidence']} with confidence >= 0.9 "
          f"({'Gemini' if settings.gemini_api_key else 'rules only: no GEMINI_API_KEY'})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed PayTrace demo data.")
    parser.add_argument("--reset", action="store_true", help="empty every table first")
    parser.add_argument("--no-data", action="store_true", help="skip loading the sample reports")
    args = parser.parse_args()

    if args.reset:
        print("Emptying all tables...")
        reset_database()
    print("Seeding demo users...")
    seed_users()
    print("Seeding partners, rate cards and column mappings...")
    seed_partners_rate_cards_and_mappings()
    if not args.no_data:
        print("Processing sample reports and reconciling...")
        load_sample_files()
    print("Done.")


if __name__ == "__main__":
    main()
