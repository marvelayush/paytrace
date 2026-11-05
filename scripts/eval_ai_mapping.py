"""Check the real Gemini column-mapping suggestions against the known-correct mapping of every sample layout.

Every sample report is treated as if its layout were new (no saved mapping), which is what happens when a
partner changes its format. For each file it prints which fields Gemini mapped, its confidence, the time
taken, any wrong picks, and whether the 20-row preview flagged them for the user to confirm.

Needs GEMINI_API_KEY (root .env or environment). Without it, every file falls back to fuzzy matching.

Usage (from the repository root):
    backend/.venv/Scripts/python scripts/eval_ai_mapping.py [--fuzzy]
"""

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from dotenv_loader import load_repo_env  # noqa: E402

load_repo_env(REPO_ROOT / ".env")

from app.sample_data.formats import FORMAT_CHANGED, FORMATS, FileFormat  # noqa: E402
from app.services.mapping_ai import FuzzySuggester, LLMSuggester, MappingSuggestion  # noqa: E402
from app.services.mappings import build_preview  # noqa: E402
from app.services.parsing import headers_of, read_table, sample_rows  # noqa: E402

import polars as pl  # noqa: E402

SAMPLE_DIR = REPO_ROOT / "sample_data"
MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"


HARD_PATHS: dict[str, Path] = {}


def file_path(fmt: FileFormat) -> Path:
    if fmt.filename in HARD_PATHS:
        return HARD_PATHS[fmt.filename]
    if fmt is FORMAT_CHANGED:
        return SAMPLE_DIR / "format_changed" / fmt.filename
    return SAMPLE_DIR / fmt.filename


def build_hard_cases(folder: Path) -> list[FileFormat]:
    """Two deliberately ambiguous layouts, to see what the AI gets wrong and whether the preview catches it.

    1. Settlement with terse, cryptic headers ("Amt1", "Tax A", "Tax B"): only the values tell TCS from TDS.
    2. COD remittance with decoys: an "Order Value" column next to the collected amount, and a
       "Batch Date" column that holds week codes, not dates.
    """
    settlement = pl.read_csv(SAMPLE_DIR / "format_changed" / FORMAT_CHANGED.filename, infer_schema=False)
    settlement = settlement.select(
        pl.col("Reference No").alias("Ref"),
        pl.col("Order Reference").alias("Ord"),
        pl.col("Payout Date").alias("Dt"),
        pl.col("Gross Sales").alias("Amt1"),
        pl.col("Platform Commission").alias("Comm"),
        pl.col("Fees & Charges").alias("Chg"),
        pl.col("TDS Withheld").alias("Tax A"),
        pl.col("TCS Withheld").alias("Tax B"),
        pl.col("Amount Credited").alias("Amt2"),
    )
    cryptic = FileFormat("Marketplace 1", "settlement", "HARD_cryptic_settlement.csv", [
        ("reference", "Ref"), ("order_id", "Ord"), ("settlement_date", "Dt"), ("gross", "Amt1"),
        ("commission", "Comm"), ("fees", "Chg"), ("tds", "Tax A"), ("tcs", "Tax B"), ("net", "Amt2"),
    ])
    cod = pl.read_csv(SAMPLE_DIR / "courierA_cod_remittance.csv", infer_schema=False)
    cod = cod.select(
        pl.lit("W39").alias("Batch Date"),
        pl.col("AWB No").alias("Tracking"),
        pl.col("Order Ref").alias("Ref"),
        pl.col("COD Amount").alias("Order Value"),
        pl.col("COD Amount").alias("Collected"),
        pl.col("Remittance Date").alias("Value Date"),
        pl.col("UTR No").alias("Bank Txn"),
    )
    decoys = FileFormat("Courier A", "cod_remittance", "HARD_decoy_cod_remittance.csv", [
        (None, "Batch Date"), ("awb", "Tracking"), ("order_id", "Ref"), (None, "Order Value"),
        ("amount", "Collected"), ("remittance_date", "Value Date"), ("utr", "Bank Txn"),
    ])
    for frame, fmt in ((settlement, cryptic), (cod, decoys)):
        path = folder / fmt.filename
        frame.write_csv(path)
        HARD_PATHS[fmt.filename] = path
    return [cryptic, decoys]


def evaluate(fmt: FileFormat, use_fuzzy: bool) -> dict:
    frame = read_table(file_path(fmt), max_rows=200)
    headers = headers_of(frame)
    rows = sample_rows(frame, 20)
    expected = fmt.mapping()["columns"]

    started = time.perf_counter()
    error = None
    if use_fuzzy:
        suggestion = FuzzySuggester().suggest(fmt.file_kind, headers, rows)
    else:
        suggester = LLMSuggester(
            api_key=os.environ["GEMINI_API_KEY"],
            model=MODEL,
            thinking_level=os.environ.get("GEMINI_THINKING_LEVEL", "low") or None,
        )
        try:
            suggestion = suggester._ask_model(fmt.file_kind, headers, rows)
        except Exception as failure:  # noqa: BLE001 - report it and use what the app would show
            error = f"{type(failure).__name__}: {str(failure).splitlines()[0][:160]}"
            suggestion = suggester.suggest(fmt.file_kind, headers, rows)
    seconds = time.perf_counter() - started

    preview = build_preview(frame, fmt.file_kind, suggestion.columns(), suggestion)
    flagged = {field["name"] for field in preview["fields"] if field["needs_confirmation"]}

    wrong = []
    for name, item in suggestion.fields.items():
        correct = expected.get(name)
        if item.source_column != correct:
            wrong.append({
                "field": name,
                "suggested": item.source_column,
                "correct": correct,
                "confidence": item.confidence,
                "flagged": name in flagged,
            })
    mapped = [item for item in suggestion.fields.values() if item.source_column]
    return {
        "file": fmt.filename,
        "kind": fmt.file_kind,
        "engine": suggestion.engine,
        "error": error,
        "seconds": seconds,
        "fields": len(suggestion.fields),
        "correct": len(suggestion.fields) - len(wrong),
        "mapped": len(mapped),
        "min_confidence": min((item.confidence for item in mapped), default=0.0),
        "mean_confidence": sum(item.confidence for item in mapped) / len(mapped) if mapped else 0.0,
        "flagged": sorted(flagged),
        "wrong": wrong,
        "preview_rows_with_errors": preview["rows_with_errors"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fuzzy", action="store_true", help="evaluate the fuzzy fallback instead of Gemini")
    parser.add_argument("--hard-only", action="store_true", help="only the two deliberately ambiguous layouts")
    parser.add_argument("--pause", type=float, default=13.0, help="seconds between Gemini calls (free tier allows ~5 per minute)")
    args = parser.parse_args()
    if not args.fuzzy and not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY is not set")
    print(f"Engine: {'fuzzy' if args.fuzzy else MODEL}", end="\n\n")
    results = []
    hard = build_hard_cases(Path(tempfile.mkdtemp(prefix="paytrace_eval_")))
    layouts = hard if args.hard_only else [FORMAT_CHANGED, *FORMATS, *hard]
    for index, fmt in enumerate(layouts):
        if index and not args.fuzzy:
            time.sleep(args.pause)
        results.append(evaluate(fmt, args.fuzzy))
    total_fields = sum(result["fields"] for result in results)
    total_correct = sum(result["correct"] for result in results)
    for result in results:
        status = "OK " if not result["wrong"] else "MISS"
        print(
            f"{status} {result['file']:<42} {result['engine']:<5} {result['seconds']:5.2f}s "
            f"{result['correct']}/{result['fields']} right, mapped {result['mapped']}, "
            f"conf min {result['min_confidence']:.2f} mean {result['mean_confidence']:.2f}, "
            f"flagged {result['flagged'] or '-'}, preview rows with errors {result['preview_rows_with_errors']}"
        )
        if result["error"]:
            print(f"    model call failed: {result['error']}")
        for item in result["wrong"]:
            print(
                f"    {item['field']}: suggested {item['suggested']!r} (conf {item['confidence']:.2f}), "
                f"correct {item['correct']!r}, flagged for review: {item['flagged']}"
            )
    seconds = [result["seconds"] for result in results]
    print(
        f"\n{len(results)} files, {total_correct}/{total_fields} fields right "
        f"({100 * total_correct / total_fields:.1f}%), time per file min {min(seconds):.2f}s "
        f"median {sorted(seconds)[len(seconds) // 2]:.2f}s max {max(seconds):.2f}s"
    )
    unflagged = [item for result in results for item in result["wrong"] if not item["flagged"]]
    print(f"Wrong picks not flagged for review: {len(unflagged)}")


if __name__ == "__main__":
    main()
