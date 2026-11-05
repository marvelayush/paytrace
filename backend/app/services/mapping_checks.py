"""Plausibility checks on a proposed mapping: rules that catch columns which parse fine but are the wrong ones.

Per-cell validation (is it a date, is it an amount) cannot tell two amount columns apart. These checks use
how settlement amounts relate to each other, on the typed preview rows. They are rules, not AI, and a
warning only asks the user to confirm the field; it never changes the mapping.

Found with the real Gemini model: given headers "Tax A" / "Tax B", it swapped TCS and TDS at confidence
0.70, just above the review threshold, and every cell still parsed (docs/PROGRESS.md, Milestone 10b).
"""

import polars as pl

# Rows where gross minus every deduction differs from net by more than this are counted as not adding up.
ARITHMETIC_TOLERANCE_PAISE = 100
# Warn when at least this share of preview rows does not add up.
ARITHMETIC_MIN_SHARE = 0.5


def _median(frame: pl.DataFrame, name: str) -> float | None:
    values = frame.get_column(name).drop_nulls()
    values = values.filter(values != 0)
    if values.len() == 0:
        return None
    return float(values.median())  # type: ignore[arg-type]


def _percent_of_gross(frame: pl.DataFrame, name: str) -> float | None:
    both = frame.select(pl.col(name), pl.col("gross")).drop_nulls().filter((pl.col("gross") > 0) & (pl.col(name) != 0))
    if both.height == 0:
        return None
    return float((both.get_column(name) / both.get_column("gross")).median()) * 100  # type: ignore[arg-type]


def _tax_swap_warning(frame: pl.DataFrame, columns: dict[str, str | None]) -> dict[str, str]:
    """GST TCS (0.5%) is withheld at a higher rate than income-tax TDS (0.1%) on the same sale (A6)."""
    if not columns.get("tcs") or not columns.get("tds"):
        return {}
    tcs, tds = _median(frame, "tcs"), _median(frame, "tds")
    if tcs is None or tds is None or tcs >= tds:
        return {}
    tcs_share, tds_share = _percent_of_gross(frame, "tcs"), _percent_of_gross(frame, "tds")
    shares = ""
    if tcs_share is not None and tds_share is not None:
        shares = f" ('{columns['tcs']}' is about {tcs_share:.2f}% of gross, '{columns['tds']}' about {tds_share:.2f}%)"
    message = (
        f"TDS is larger than TCS in these rows{shares}. TCS is normally the larger of the two, "
        "so the TCS and TDS columns may be swapped."
    )
    return {"tcs": message, "tds": message}


def _arithmetic_warning(frame: pl.DataFrame, columns: dict[str, str | None]) -> dict[str, str]:
    """Gross minus commission, fees, TCS and TDS should equal net on a settlement line."""
    if not columns.get("gross") or not columns.get("net"):
        return {}
    deductions = [name for name in ("commission", "fees", "tcs", "tds") if columns.get(name)]
    rows = frame.select(["gross", "net", *deductions]).drop_nulls(["gross", "net"])
    if rows.height == 0:
        return {}
    computed = pl.col("gross") - pl.sum_horizontal([pl.col(name).fill_null(0) for name in deductions] or [pl.lit(0)])
    off = rows.select(((computed - pl.col("net")).abs() > ARITHMETIC_TOLERANCE_PAISE).sum()).item()
    if off / rows.height < ARITHMETIC_MIN_SHARE:
        return {}
    message = (
        f"In {off} of {rows.height} preview rows, gross minus the mapped deductions does not equal net. "
        "One of the amount columns may be the wrong one."
    )
    return {"net": message}


def plausibility_warnings(file_kind: str, typed: pl.DataFrame, columns: dict[str, str | None]) -> dict[str, str]:
    """Field name -> warning for the user. Empty when nothing looks off."""
    if file_kind != "settlement":
        return {}
    warnings: dict[str, str] = {}
    warnings.update(_arithmetic_warning(typed, columns))
    warnings.update(_tax_swap_warning(typed, columns))
    return warnings
