"""Measure the review-queue suggestions against the sample data's ground truth.

The generator records which order each ID-less line really belongs to. This script re-runs the rule
shortlist (and the AI, when GEMINI_API_KEY is set) on the seeded database and reports, per engine:
how often the true order is shortlisted, how often the suggestion is right, and how many wrong
suggestions carry a confidence high enough for bulk accept. It changes suggestions only, never decisions.

Usage (from the repository root, after scripts/seed.py):
    backend/.venv/Scripts/python scripts/eval_match_suggestions.py [--rules-only]
"""

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
os.chdir(REPO_ROOT / "backend")

from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env(REPO_ROOT / ".env")

from sqlalchemy import text  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.sample_data.generator import generate  # noqa: E402
from app.services.match_ai import get_ranker  # noqa: E402
from app.services.review_queue import BULK_ACCEPT_MIN_CONFIDENCE, refresh_suggestions  # noqa: E402


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Score review-queue suggestions against the sample truth.")
    parser.add_argument("--rules-only", action="store_true", help="do not call the AI")
    args = parser.parse_args()

    # Same arguments as scripts/generate_sample_data.py, so the truth matches the committed files.
    data = generate(n_orders=30_000, seed=20261001, missing_id_share=0.003, ambiguous_pairs=3)
    truth = {(line["kind"], line["reference"]): line for line in data.missing_ids}

    settings = get_settings()
    ranker = None if args.rules_only else get_ranker(settings.gemini_api_key, settings.gemini_model, settings.gemini_thinking_level or None)
    with SessionLocal() as db:
        refresh_suggestions(db, ranker=ranker)
        db.commit()
        lines = db.execute(text(
            "SELECT kind, reference, suggested_order_id, confidence, engine, candidates_json FROM unmatched_lines WHERE status = 'open'"
        )).all()

    shortlisted = right = rule_top_right = confident = confident_wrong = ambiguous_confident = 0
    for line in lines:
        expected = truth[(line.kind, line.reference)]
        candidate_ids = [candidate["order_id"] for candidate in line.candidates_json]
        shortlisted += expected["order_id"] in candidate_ids
        right += line.suggested_order_id == expected["order_id"]
        rule_top_right += bool(candidate_ids) and candidate_ids[0] == expected["order_id"]
        if (line.confidence or 0) >= BULK_ACCEPT_MIN_CONFIDENCE:
            confident += 1
            confident_wrong += line.suggested_order_id != expected["order_id"]
            ambiguous_confident += expected["ambiguous"]

    engines = sorted({line.engine for line in lines})
    print(f"{len(lines)} open lines, engine: {', '.join(engines)}")
    print(f"  true order in the rule shortlist: {shortlisted}/{len(lines)}")
    print(f"  rule top pick right:              {rule_top_right}/{len(lines)}")
    print(f"  suggestion right:                 {right}/{len(lines)}")
    print(f"  confidence >= {BULK_ACCEPT_MIN_CONFIDENCE}: {confident} lines, {confident_wrong} wrong, {ambiguous_confident} of the look-alike pairs")


if __name__ == "__main__":
    main()
