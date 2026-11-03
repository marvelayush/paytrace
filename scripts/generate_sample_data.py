"""Generate a realistic month of partner files for the demo.

Writes one file per partner report into sample_data/ (14 CSV + 1 Excel + 1 warehouse file),
each in that partner's own layout, plus sample_data/format_changed/ with a Marketplace 1 settlement
report whose columns were renamed and reordered (to demo AI column mapping).

Usage (from the repository root):
    backend/.venv/Scripts/python scripts/generate_sample_data.py              # Windows
    backend/.venv/bin/python scripts/generate_sample_data.py --orders 30000   # macOS / Linux
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.sample_data.formats import write_all  # noqa: E402
from app.sample_data.generator import generate  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--orders", type=int, default=30_000, help="number of orders (default 30,000)")
    parser.add_argument("--seed", type=int, default=20261001, help="random seed, for repeatable files")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "sample_data", help="output folder")
    args = parser.parse_args()

    data = generate(n_orders=args.orders, seed=args.seed)
    paths = write_all(data, args.out)

    leaks_by_type: dict[str, list[int]] = defaultdict(list)
    for _, leak_type, amount in data.injected:
        leaks_by_type[leak_type].append(amount)
    leak_share = data.leak_value_paise / data.order_value_paise

    manifest = {
        "period": {"from": data.start.isoformat(), "to": data.end.isoformat()},
        "orders": len(data.orders),
        "orders_by_channel": dict(Counter(order["channel"] for order in data.orders)),
        "order_value_rupees": round(data.order_value_paise / 100, 2),
        "injected_leakage": {
            leak_type: {"orders": len(amounts), "rupees": round(sum(amounts) / 100, 2)}
            for leak_type, amounts in sorted(leaks_by_type.items())
        },
        "leakage_rupees": round(data.leak_value_paise / 100, 2),
        "leakage_share_of_value": round(leak_share, 4),
        "files": sorted(str(path.relative_to(args.out)).replace("\\", "/") for path in paths),
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"{len(data.orders):,} orders, {data.start} to {data.end}, value ₹{data.order_value_paise / 100:,.0f}")
    for leak_type, info in manifest["injected_leakage"].items():
        print(f"  {leak_type:<20} {info['orders']:>5} orders  ₹{info['rupees']:>12,.2f}")
    print(f"  total leakage ₹{data.leak_value_paise / 100:,.0f} = {leak_share:.2%} of order value")
    print(f"Wrote {len(paths)} files to {args.out}")


if __name__ == "__main__":
    main()
