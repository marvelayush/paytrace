"""Prove the brief's hard part: 1 lakh rows matched in under a minute.

Generates 100,000 orders with ~1.5% injected leakage in every partner's file format, then runs the
real pipeline (parse -> normalise -> COPY -> match -> COPY results) against a separate `paytrace_bench`
database, prints timings per stage and writes docs/BENCHMARK.md.

Usage (from the repository root, with docker compose up):
    backend/.venv/Scripts/python scripts/benchmark_matching.py [--orders 100000]
"""

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
os.chdir(REPO_ROOT / "backend")

from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env(REPO_ROOT / ".env")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

# Never touch the dev database: point the app at paytrace_bench before it is imported.
dev_url = make_url(os.environ.get("DATABASE_URL", "postgresql+psycopg://paytrace:paytrace@localhost:5432/paytrace"))
bench_url = dev_url.set(database="paytrace_bench")
os.environ["DATABASE_URL"] = bench_url.render_as_string(hide_password=False)


def ensure_database() -> None:
    admin = create_engine(dev_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        if not connection.scalar(text("SELECT 1 FROM pg_database WHERE datname = 'paytrace_bench'")):
            connection.execute(text('CREATE DATABASE "paytrace_bench"'))
    admin.dispose()

    from alembic import command
    from alembic.config import Config

    config = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
    config.attributes["database_url"] = os.environ["DATABASE_URL"]
    command.upgrade(config, "head")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--orders", type=int, default=100_000)
    parser.add_argument("--no-report", action="store_true", help="do not rewrite docs/BENCHMARK.md")
    args = parser.parse_args()

    ensure_database()
    from app.benchmark import markdown_report, run_benchmark
    from app.db import SessionLocal

    work_dir = REPO_ROOT / "sample_data" / "benchmark"  # gitignored
    with SessionLocal() as db:
        result = run_benchmark(db, work_dir, n_orders=args.orders)

    print(f"{result.orders:,} orders, {result.rows_total:,} partner rows")
    print(f"  ingest (parse + normalise + COPY): {result.ingest_s:6.2f} s")
    for stage, ms in result.recon_stage_ms.items():
        print(f"  reconcile {stage:<5}:                  {ms / 1000:6.2f} s")
    print(f"  END TO END:                         {result.end_to_end_s:6.2f} s  (target < 60 s)")
    print(f"  leaks flagged {result.caught:,}/{result.injected:,}, false alarms {result.false_alarms}, auto-matched {result.auto_matched_pct}%")

    if not args.no_report:
        report = REPO_ROOT / "docs" / "BENCHMARK.md"
        report.write_text(markdown_report(result), encoding="utf-8")
        print(f"Wrote {report}")


if __name__ == "__main__":
    main()
