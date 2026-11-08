"""Review queue: suggested orders for settlement and COD lines that arrived without an order ID.

Step 1, rules (deterministic, vectorised): for each line, shortlist up to five orders that
  - belong to the same partner (the channel for a settlement line, the courier for COD, which must be a COD order),
  - were delivered and have not been paid by that kind of line yet,
  - match the amount within a tolerance (gross vs order value; or net vs expected net; COD amount vs order value),
  - were paid in a plausible window: from delivery to the due date plus 30 days,
  - or carry the same AWB as the line (an exact AWB match is a certain candidate).
  Rule score = 0.6 x amount closeness + 0.4 x closeness to the due date. Confidence from the rules = top score
  minus half the runner-up's, so two look-alike candidates can never look certain (A45).
Step 2, AI (optional): `match_ai` ranks the shortlist with a confidence and a one-line reason. How its answer
  is used was decided by measuring it against the sample data's ground truth (scripts/eval_match_suggestions.py, A46):
  - among candidates the rules cannot tell apart (exact tie), the AI's pick is the suggestion;
  - when the AI disagrees with a clear rule winner, the rule pick stays and the disagreement is shown, with lower
    confidence. On the sample data the rules were right every time the two disagreed;
  - the AI's confidence never exceeds what the evidence allows (`evidence_cap`). Uncapped, it was confident and
    wrong on 5 of 82 lines, which bulk accept would have linked.

Nothing here links a line to an order. Only `accept_line` (a finance executive's click) does that, and it is audited.
"""

import hashlib
import json
from datetime import date, datetime, timezone

import polars as pl
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Partner, UnmatchedLine, User
from app.services.audit import record_audit
from app.services.ingest import COD_HASH_COLUMNS, SETTLEMENT_HASH_COLUMNS
from app.services.match_ai import CANDIDATE_FIELDS, MatchRanker, RankItem, Ranking
from app.services.matching import load_frame

MAX_CANDIDATES = 5
AMOUNT_TOLERANCE_PAISE = 1_000  # ₹10, the brief's gap threshold ...
AMOUNT_TOLERANCE_SHARE = 0.02  # ... or 2% of the line, whichever is larger
LATE_WINDOW_DAYS = 30  # a line may arrive up to this long after the due date
BULK_ACCEPT_MIN_CONFIDENCE = 0.9
TIE_MARGIN = 0.005  # rule scores this close are a tie: the data cannot tell the candidates apart
AI_DISAGREES_CAP = 0.6  # confidence when the AI prefers a candidate the rules rate clearly lower


# ---------- step 1: rules ----------

LINE_SCHEMA = {"id": pl.Int64, "partner_id": pl.Int64, "kind": pl.String, "line_date": pl.Date,
               "gross_paise": pl.Int64, "amount_paise": pl.Int64, "awb": pl.String}
POOL_SCHEMA = {"order_id": pl.String, "channel_partner_id": pl.Int64, "courier_partner_id": pl.Int64, "payment_mode": pl.String,
               "order_date": pl.Date, "delivered_date": pl.Date, "value_paise": pl.Int64, "expected_net_paise": pl.Int64,
               "awb": pl.String, "has_settlement": pl.Boolean, "has_cod": pl.Boolean}


def shortlist(lines: pl.DataFrame, pool: pl.DataFrame, settlement_days: dict[int, int]) -> pl.DataFrame:
    """Pure function: one row per (line, candidate), best first, at most MAX_CANDIDATES per line.

    Columns: line_id, order_id, rule_score, amount_diff_paise, due_date, days_from_due, awb_match. The due date uses
    the settlement cycle of the partner who sent the line (the courier for COD), not the sales channel's.
    """
    if lines.is_empty() or pool.is_empty():
        return pl.DataFrame(schema={"line_id": pl.Int64, "order_id": pl.String, "rule_score": pl.Float64,
                                    "amount_diff_paise": pl.Int64, "due_date": pl.Date, "days_from_due": pl.Int64, "awb_match": pl.Boolean})
    days = pl.DataFrame({"partner_id": list(settlement_days), "settlement_days": list(settlement_days.values())},
                        schema={"partner_id": pl.Int64, "settlement_days": pl.Int64})
    lines = lines.rename({"id": "line_id", "awb": "line_awb"}).join(days, on="partner_id", how="left").with_columns(
        pl.col("settlement_days").fill_null(7)
    )
    settlement = lines.filter(pl.col("kind") == "settlement").join(
        pool.filter(~pl.col("has_settlement")), left_on="partner_id", right_on="channel_partner_id", how="inner"
    )
    cod = lines.filter(pl.col("kind") == "cod_remittance").join(
        pool.filter(~pl.col("has_cod") & (pl.col("payment_mode") == "cod")), left_on="partner_id", right_on="courier_partner_id", how="inner"
    )
    pairs = pl.concat([settlement.select(_PAIR_COLUMNS), cod.select(_PAIR_COLUMNS)], how="vertical")

    # What the line's amount is compared with: gross vs order value, net vs expected net, COD cash vs order value.
    use_gross = (pl.col("kind") == "settlement") & (pl.col("gross_paise") != 0)
    line_amount = pl.when(use_gross).then(pl.col("gross_paise")).otherwise(pl.col("amount_paise"))
    order_amount = (
        pl.when(use_gross | (pl.col("kind") == "cod_remittance")).then(pl.col("value_paise"))
        .otherwise(pl.col("expected_net_paise"))
    )
    tolerance = pl.max_horizontal(pl.lit(AMOUNT_TOLERANCE_PAISE), (line_amount.abs() * AMOUNT_TOLERANCE_SHARE).cast(pl.Int64))
    due = pl.col("delivered_date") + pl.duration(days=pl.col("settlement_days"))
    awb_match = pl.col("line_awb").is_not_null() & (pl.col("line_awb") == pl.col("awb"))

    scored = pairs.with_columns(
        (line_amount - order_amount).alias("amount_diff_paise"),
        tolerance.alias("tolerance"),
        due.alias("due_date"),
        (pl.col("line_date") - due).dt.total_days().alias("days_from_due"),
        awb_match.fill_null(False).alias("awb_match"),
    ).filter(
        pl.col("awb_match")
        | (
            (pl.col("amount_diff_paise").abs() <= pl.col("tolerance"))
            & (pl.col("line_date") >= pl.col("delivered_date"))
            & (pl.col("days_from_due") <= LATE_WINDOW_DAYS)
        )
    ).with_columns(
        pl.when(pl.col("awb_match")).then(1.0).otherwise(
            0.6 * (1 - pl.col("amount_diff_paise").abs() / pl.col("tolerance"))
            + 0.4 * (1 - (pl.col("days_from_due").abs() / LATE_WINDOW_DAYS).clip(0, 1))
        ).round(3).alias("rule_score")
    )
    ranked = scored.sort(["line_id", "rule_score", "order_id"], descending=[False, True, False])
    return ranked.group_by("line_id", maintain_order=True).head(MAX_CANDIDATES).select(
        "line_id", "order_id", "rule_score", "amount_diff_paise", "due_date", "days_from_due", "awb_match"
    )


_PAIR_COLUMNS = ["line_id", "partner_id", "kind", "line_date", "gross_paise", "amount_paise", "line_awb", "settlement_days",
                 "order_id", "delivered_date", "value_paise", "expected_net_paise", "awb"]


def rule_confidence(scores: list[float]) -> float:
    """Top score minus half the runner-up's: one clear candidate is near 1, two look-alikes stay near 0.5."""
    if not scores:
        return 0.0
    second = scores[1] if len(scores) > 1 else 0.0
    return round(max(scores[0] - 0.5 * second, 0.0), 2)


def rule_reason(candidates: list[dict]) -> str:
    if not candidates:
        return "No order fits the partner, amount and date window."
    top = candidates[0]
    if top["awb_match"]:
        return "Same AWB as the line."
    diff = abs(top["amount_diff_paise"]) / 100
    amount = "Amount matches exactly" if diff == 0 else f"Amount within ₹{diff:,.2f}"
    days = top["days_from_due"]
    timing = "paid on the due date" if days == 0 else (f"paid {days} days after the due date" if days > 0 else f"paid {-days} days before the due date")
    others = len(candidates) - 1
    if others and candidates[1]["rule_score"] >= top["rule_score"] - TIE_MARGIN:
        return f"{amount}, {timing}; {others} other order(s) look the same: check before accepting."
    tail = f"; {others} weaker candidate(s)" if others else "; the only candidate"
    return f"{amount}, {timing}{tail}."


def evidence_cap(candidates: list[dict], order_id: str) -> float:
    """The most confidence the rule evidence allows for one candidate: its score minus half the best other's."""
    picked = next(candidate["rule_score"] for candidate in candidates if candidate["order_id"] == order_id)
    others = [candidate["rule_score"] for candidate in candidates if candidate["order_id"] != order_id]
    return round(max(picked - 0.5 * max(others, default=0.0), 0.0), 2)


def combine(candidates: list[dict], ranking: Ranking | None) -> tuple[str | None, float, str, str, str | None]:
    """(suggested order, confidence, reason, engine, the AI's own pick) from the rule shortlist and the AI's ranking.

    See the module notes (A46): the AI breaks exact ties and explains; it never overrules a clear rule winner,
    and never claims more certainty than the evidence allows, so bulk accept (>= 0.9) needs one clear candidate.
    """
    scores = [candidate["rule_score"] for candidate in candidates]
    rule_top = candidates[0]["order_id"] if candidates else None
    if ranking is None or not candidates:
        return rule_top, rule_confidence(scores), rule_reason(candidates), "rules", None
    if ranking.order_id is None:
        reason = f"The AI found no good fit ({ranking.reason.rstrip('.')}). Rules suggest {rule_top}."
        return rule_top, min(rule_confidence(scores), AI_DISAGREES_CAP), reason, "llm", None
    tied_with_top = [candidate["order_id"] for candidate in candidates if candidate["rule_score"] >= scores[0] - TIE_MARGIN]
    if ranking.order_id in tied_with_top:
        confidence = min(ranking.confidence, evidence_cap(candidates, ranking.order_id))
        return ranking.order_id, round(confidence, 2), ranking.reason, "llm", ranking.order_id
    reason = f"Rules prefer {rule_top} (closer amount and date). The AI preferred {ranking.order_id}: {ranking.reason}"
    return rule_top, min(rule_confidence(scores), AI_DISAGREES_CAP), reason, "llm", ranking.order_id


# ---------- loading, refreshing ----------

POOL_QUERY = """
SELECT o.order_id, o.channel_partner_id, o.courier_partner_id, o.payment_mode, o.order_date, o.delivered_date, o.value_paise,
       COALESCE((r.expected_breakdown_json->>'value')::bigint - (r.expected_breakdown_json->>'commission')::bigint
                - (r.expected_breakdown_json->>'fixed_fee')::bigint - (r.expected_breakdown_json->>'gateway_fee')::bigint
                - (r.expected_breakdown_json->>'tcs')::bigint - (r.expected_breakdown_json->>'tds')::bigint, o.value_paise) AS expected_net_paise,
       o.awb,
       -- Text booleans: COPY writes t/f, which the CSV reader does not take as booleans.
       CASE WHEN s.order_id IS NOT NULL THEN 'true' ELSE 'false' END AS has_settlement,
       CASE WHEN c.order_id IS NOT NULL OR ca.awb IS NOT NULL THEN 'true' ELSE 'false' END AS has_cod
FROM orders o
LEFT JOIN recon_results r ON r.order_id = o.order_id
LEFT JOIN (SELECT DISTINCT order_id FROM settlement_lines) s ON s.order_id = o.order_id
LEFT JOIN (SELECT DISTINCT order_id FROM cod_remittances WHERE order_id IS NOT NULL) c ON c.order_id = o.order_id
LEFT JOIN (SELECT DISTINCT awb FROM cod_remittances WHERE awb IS NOT NULL) ca ON ca.awb = o.awb
WHERE o.delivery_status = 'delivered'
"""


def _load_lines(db: Session, line_ids: list[int] | None) -> pl.DataFrame:
    where = "status = 'open'" + (f" AND id IN ({', '.join(str(int(i)) for i in line_ids) or 'NULL'})" if line_ids is not None else "")
    return load_frame(db, f"SELECT id, partner_id, kind, line_date, gross_paise, amount_paise, awb FROM unmatched_lines WHERE {where}", LINE_SCHEMA)


def _candidate_details(db: Session, order_ids: list[str]) -> dict[str, dict]:
    if not order_ids:
        return {}
    rows = db.execute(text("""
        SELECT o.order_id, o.order_date, o.delivered_date, o.value_paise, o.awb, o.payment_mode, p.name AS partner_name,
               COALESCE((r.expected_breakdown_json->>'value')::bigint - (r.expected_breakdown_json->>'commission')::bigint
                - (r.expected_breakdown_json->>'fixed_fee')::bigint - (r.expected_breakdown_json->>'gateway_fee')::bigint
                - (r.expected_breakdown_json->>'tcs')::bigint - (r.expected_breakdown_json->>'tds')::bigint, o.value_paise) AS expected_net_paise,
               r.status AS recon_status
        FROM orders o JOIN partners p ON p.id = o.channel_partner_id
        LEFT JOIN recon_results r ON r.order_id = o.order_id
        WHERE o.order_id = ANY(:ids)"""), {"ids": order_ids}).mappings().all()
    return {row["order_id"]: dict(row) for row in rows}


def refresh_suggestions(db: Session, ranker: MatchRanker | None = None, line_ids: list[int] | None = None) -> int:
    """Rule shortlist (and, with a ranker, AI ranking) for open lines. Returns how many lines were updated.

    Only suggestions change here: status stays `open`, and no line reaches the ledger.
    """
    lines = _load_lines(db, line_ids)
    if lines.is_empty():
        return 0
    pool = load_frame(db, POOL_QUERY, POOL_SCHEMA)
    settlement_days = dict(db.execute(select(Partner.id, Partner.settlement_days)).all())
    pairs = shortlist(lines, pool, settlement_days)
    by_line: dict[int, list[dict]] = {line_id: [] for line_id in lines["id"].to_list()}
    for row in pairs.to_dicts():
        by_line[row["line_id"]].append(
            {key: row[key] for key in ("order_id", "rule_score", "amount_diff_paise", "due_date", "days_from_due", "awb_match")}
        )

    outcome = None
    if ranker is not None:
        details = _candidate_details(db, list({c["order_id"] for cands in by_line.values() for c in cands}))
        line_rows = {row["id"]: row for row in lines.to_dicts()}
        partner_names = dict(db.execute(select(Partner.id, Partner.name)).all())
        items = [
            RankItem(line_id=line_id, line=_line_for_ai(line_rows[line_id], partner_names), candidates=[_candidate_for_ai(details[c["order_id"]], c) for c in cands])
            for line_id, cands in by_line.items() if cands
        ]
        outcome = ranker.rank(items) if items else None

    for line_id, candidates in by_line.items():
        ranking = outcome.rankings.get(line_id) if outcome else None
        suggested, confidence, reason, engine, ai_pick = combine(candidates, ranking)
        for candidate in candidates:
            candidate["ai_pick"] = candidate["order_id"] == ai_pick
        note = outcome.notes.get(line_id) if outcome else None
        db.execute(text("""
            UPDATE unmatched_lines SET candidates_json = CAST(:candidates AS jsonb), suggested_order_id = :suggested,
                   confidence = :confidence, reason = :reason, engine = :engine, ai_note = :note
            WHERE id = :id AND status = 'open'"""),
            {"candidates": _json(candidates), "suggested": suggested, "confidence": confidence, "reason": reason,
             "engine": engine, "note": note, "id": line_id})
    return len(by_line)


def _json(value) -> str:
    return json.dumps(value, default=str)


def _rupees(paise: int | None) -> float | None:
    return None if paise is None else round(paise / 100, 2)


def _line_for_ai(line: dict, partner_names: dict[int, str]) -> dict:
    return {"kind": line["kind"], "partner": partner_names.get(line["partner_id"]), "line_date": line["line_date"],
            "gross_rupees": _rupees(line["gross_paise"]) if line["kind"] == "settlement" else None,
            "amount_rupees": _rupees(line["amount_paise"]), "awb": line["awb"], "reference": None}


def _candidate_for_ai(detail: dict, signals: dict) -> dict:
    candidate = {
        "order_id": detail["order_id"], "order_date": detail["order_date"], "delivered_date": detail["delivered_date"],
        "due_date": signals["due_date"], "value_rupees": _rupees(detail["value_paise"]),
        "expected_net_rupees": _rupees(detail["expected_net_paise"]), "awb": detail["awb"], "payment_mode": detail["payment_mode"],
        "days_from_due": signals["days_from_due"], "amount_diff_rupees": _rupees(signals["amount_diff_paise"]),
    }
    return {name: candidate[name] for name in CANDIDATE_FIELDS}


# ---------- people's decisions ----------

class QueueError(ValueError):
    pass


def _line_hash(line: UnmatchedLine, order_id: str) -> str:
    """Same md5 as ingestion would give this line had the partner sent the order ID (no double counting later)."""
    if line.kind == "settlement":
        values = {"order_id": order_id, "settlement_date": line.line_date, "gross": line.gross_paise, "commission": line.commission_paise,
                  "fees": line.fees_paise, "tcs": line.tcs_paise, "tds": line.tds_paise, "net": line.amount_paise, "reference": line.reference}
        columns = SETTLEMENT_HASH_COLUMNS
    else:
        values = {"order_id": order_id, "awb": line.awb, "remittance_date": line.line_date, "amount": line.amount_paise, "utr": line.reference}
        columns = COD_HASH_COLUMNS
    key = "|".join("" if values[name] is None else (values[name].isoformat() if isinstance(values[name], date) else str(values[name])) for name in columns)
    return hashlib.md5(key.encode()).hexdigest()


def _write_to_ledger(db: Session, line: UnmatchedLine, order_id: str) -> None:
    params = {"upload_id": line.upload_id, "partner_id": line.partner_id, "order_id": order_id, "line_date": line.line_date,
              "amount": line.amount_paise, "reference": line.reference, "hash": _line_hash(line, order_id), "row": line.row_number}
    if line.kind == "settlement":
        db.execute(text("""
            INSERT INTO settlement_lines (upload_id, partner_id, order_id, settlement_date, gross_paise, commission_paise, fees_paise,
                                          tcs_paise, tds_paise, net_paise, raw_ref, line_hash, row_number)
            VALUES (:upload_id, :partner_id, :order_id, :line_date, :gross, :commission, :fees, :tcs, :tds, :amount, :reference, :hash, :row)
            ON CONFLICT (partner_id, line_hash) DO NOTHING"""),
            {**params, "gross": line.gross_paise, "commission": line.commission_paise, "fees": line.fees_paise,
             "tcs": line.tcs_paise, "tds": line.tds_paise})
    else:
        db.execute(text("""
            INSERT INTO cod_remittances (upload_id, courier_partner_id, order_id, awb, remittance_date, amount_paise, utr, line_hash, row_number)
            VALUES (:upload_id, :partner_id, :order_id, :awb, :line_date, :amount, :reference, :hash, :row)
            ON CONFLICT (courier_partner_id, line_hash) DO NOTHING"""), {**params, "awb": line.awb})


def _snapshot(line: UnmatchedLine) -> dict:
    return {"status": line.status, "suggested_order_id": line.suggested_order_id, "confidence": line.confidence, "engine": line.engine}


def accept_line(db: Session, line: UnmatchedLine, order_id: str, user: User, note: str | None = None) -> str:
    """Link the line to one of its candidate orders (a person's decision). The caller re-matches the order."""
    if line.status != "open":
        raise QueueError(f"This line is already {line.status}.")
    candidate_ids = [candidate["order_id"] for candidate in line.candidates_json or []]
    if order_id not in candidate_ids:
        raise QueueError("Pick one of the suggested orders for this line.")
    before = _snapshot(line)
    _write_to_ledger(db, line, order_id)
    line.status = "accepted"
    line.resolved_order_id = order_id
    line.resolved_by = user.id
    line.resolved_at = datetime.now(timezone.utc)
    line.note = (note or "").strip() or None
    record_audit(db, user, "review_line_accepted", "unmatched_line", line.id, before=before,
                 after={**_snapshot(line), "order_id": order_id, "was_suggested": order_id == line.suggested_order_id, "note": line.note})
    db.flush()
    return order_id


def reject_line(db: Session, line: UnmatchedLine, user: User, note: str | None = None) -> None:
    """Leave the line unmatched on purpose (it stays out of the ledger)."""
    if line.status != "open":
        raise QueueError(f"This line is already {line.status}.")
    before = _snapshot(line)
    line.status = "rejected"
    line.resolved_by = user.id
    line.resolved_at = datetime.now(timezone.utc)
    line.note = (note or "").strip() or None
    record_audit(db, user, "review_line_rejected", "unmatched_line", line.id, before=before, after={**_snapshot(line), "note": line.note})
    db.flush()


def lines_sharing_candidates(db: Session, order_ids: list[str], exclude: list[int]) -> list[int]:
    """Open lines that still list one of these (now paid) orders: their shortlist must be refreshed."""
    if not order_ids:
        return []
    rows = db.execute(text("""
        SELECT DISTINCT l.id FROM unmatched_lines l, jsonb_array_elements(l.candidates_json) AS c
        WHERE l.status = 'open' AND c->>'order_id' = ANY(:ids) AND NOT (l.id = ANY(:exclude))"""),
        {"ids": order_ids, "exclude": exclude or [0]}).scalars().all()
    return list(rows)


# ---------- reading ----------

def queue_counts(db: Session) -> dict:
    rows = dict(db.execute(text("SELECT status, COUNT(*) FROM unmatched_lines GROUP BY status")).all())
    open_value, high, pending_ai = db.execute(text(f"""
        SELECT COALESCE(SUM(ABS(amount_paise)), 0),
               COUNT(*) FILTER (WHERE confidence >= {BULK_ACCEPT_MIN_CONFIDENCE} AND suggested_order_id IS NOT NULL),
               COUNT(*) FILTER (WHERE ai_note = 'pending')
        FROM unmatched_lines WHERE status = 'open'""")).one()
    return {"open": rows.get("open", 0), "accepted": rows.get("accepted", 0), "rejected": rows.get("rejected", 0),
            "open_value_paise": int(open_value), "high_confidence": high, "ai_pending": pending_ai,
            "bulk_accept_min_confidence": BULK_ACCEPT_MIN_CONFIDENCE}


def list_lines(db: Session, status: str, limit: int = 200) -> list[dict]:
    lines = list(db.scalars(
        select(UnmatchedLine).where(UnmatchedLine.status == status)
        .order_by(UnmatchedLine.confidence.desc().nulls_last() if status == "open" else UnmatchedLine.resolved_at.desc(), UnmatchedLine.id)
        .limit(limit)
    ))
    partner_names = dict(db.execute(select(Partner.id, Partner.name)).all())
    users = dict(db.execute(select(User.id, User.name)).all())
    files = dict(db.execute(text("SELECT id, filename FROM uploads WHERE id = ANY(:ids)"), {"ids": list({line.upload_id for line in lines}) or [0]}).all())
    order_ids = list({c["order_id"] for line in lines for c in (line.candidates_json or [])} | {line.resolved_order_id for line in lines if line.resolved_order_id})
    details = _candidate_details(db, order_ids)
    out = []
    for line in lines:
        candidates = []
        for candidate in line.candidates_json or []:
            detail = details.get(candidate["order_id"], {})
            candidates.append({
                **candidate,
                "partner_name": detail.get("partner_name"), "order_date": detail.get("order_date"),
                "delivered_date": detail.get("delivered_date"),
                "value_paise": detail.get("value_paise"), "expected_net_paise": detail.get("expected_net_paise"),
                "awb": detail.get("awb"), "payment_mode": detail.get("payment_mode"), "recon_status": detail.get("recon_status"),
            })
        out.append({
            "id": line.id, "kind": line.kind, "partner_id": line.partner_id, "partner_name": partner_names.get(line.partner_id),
            "line_date": line.line_date, "gross_paise": line.gross_paise, "commission_paise": line.commission_paise,
            "fees_paise": line.fees_paise, "tcs_paise": line.tcs_paise, "tds_paise": line.tds_paise, "amount_paise": line.amount_paise,
            "awb": line.awb, "reference": line.reference, "filename": files.get(line.upload_id), "row_number": line.row_number,
            "status": line.status, "suggested_order_id": line.suggested_order_id, "confidence": line.confidence,
            "reason": line.reason, "engine": line.engine, "ai_note": line.ai_note, "candidates": candidates,
            "resolved_order_id": line.resolved_order_id, "resolved_by": users.get(line.resolved_by), "resolved_at": line.resolved_at,
            "note": line.note,
        })
    return out
