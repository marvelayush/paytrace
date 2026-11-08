"""Review queue: rule shortlist, AI ranking and its fallback, people's decisions, never closing automatically."""

import json
from datetime import date
from pathlib import Path

import httpx
import polars as pl
import pytest
from sqlalchemy import func, select

from app.models import AuditLog, ColumnMapping, Partner, ReconResult, SettlementLine, Source, UnmatchedLine
from app.routers.review import get_match_ranker
from app.sample_data.formats import FORMATS, format_for, write_all
from app.sample_data.generator import generate
from app.services.claims import refresh_claims
from app.services.match_ai import AI_INVALID, AI_NO_KEY, AI_UNAVAILABLE, GeminiRanker, RankItem, Ranking, RuleRanker, build_prompt
from app.services.matching import run_reconciliation
from app.services.review_queue import combine, evidence_cap, refresh_suggestions, rule_confidence, shortlist
from app.services.seeding import seed_initial_mappings, seed_reference_data
from app.services.upload_processing import process_file

AS_OF = date(2026, 11, 3)

# ---------- step 1: the rule shortlist (pure) ----------

POOL_COLUMNS = {"order_id": pl.String, "channel_partner_id": pl.Int64, "courier_partner_id": pl.Int64, "payment_mode": pl.String,
                "order_date": pl.Date, "delivered_date": pl.Date, "value_paise": pl.Int64, "expected_net_paise": pl.Int64,
                "awb": pl.String, "has_settlement": pl.Boolean, "has_cod": pl.Boolean}


def _order(order_id, partner=1, courier=None, mode="prepaid", delivered=date(2026, 10, 1), value=119_900, net=85_480, awb=None,
           paid=False, cod_paid=False):
    return {"order_id": order_id, "channel_partner_id": partner, "courier_partner_id": courier, "payment_mode": mode,
            "order_date": date(2026, 9, 28), "delivered_date": delivered, "value_paise": value, "expected_net_paise": net,
            "awb": awb, "has_settlement": paid, "has_cod": cod_paid}


def _line(line_id=1, partner=1, kind="settlement", on=date(2026, 10, 8), gross=119_900, amount=85_480, awb=None):
    return {"id": line_id, "partner_id": partner, "kind": kind, "line_date": on, "gross_paise": gross, "amount_paise": amount, "awb": awb}


def _shortlist(lines, orders, days=None):
    return shortlist(pl.DataFrame(lines), pl.DataFrame(orders, schema=POOL_COLUMNS), days or {1: 7, 9: 10}).to_dicts()


def test_shortlist_keeps_only_same_partner_unpaid_orders_within_tolerance_and_window():
    orders = [
        _order("RIGHT"),
        _order("OTHER-PARTNER", partner=2),
        _order("ALREADY-PAID", paid=True),
        _order("AMOUNT-OFF", value=119_900 + 2_500),  # ₹25 off: beyond max(₹10, 2% of ₹1,199 = ₹23.98)
        _order("DELIVERED-AFTER-PAYMENT", delivered=date(2026, 10, 9)),
        _order("TOO-OLD", delivered=date(2026, 8, 1)),  # paid long after due + 30 days
    ]
    assert [row["order_id"] for row in _shortlist([_line()], orders)] == ["RIGHT"]


def test_shortlist_scores_exact_date_above_near_date_and_is_deterministic():
    orders = [_order("B-NEAR", delivered=date(2026, 9, 30)), _order("A-EXACT"), _order("C-TIE", delivered=date(2026, 10, 1))]
    rows = _shortlist([_line()], orders)
    assert [row["order_id"] for row in rows] == ["A-EXACT", "C-TIE", "B-NEAR"]  # tie broken by order ID
    assert rows[0]["rule_score"] == rows[1]["rule_score"] == 1.0
    assert rows[0]["due_date"] == date(2026, 10, 8) and rows[0]["days_from_due"] == 0
    assert _shortlist([_line()], orders) == rows


def test_shortlist_cod_uses_the_couriers_cycle_and_only_cod_orders():
    orders = [_order("COD", courier=9, mode="cod", value=99_900), _order("PREPAID", courier=9, mode="prepaid", value=99_900),
              _order("REMITTED", courier=9, mode="cod", value=99_900, cod_paid=True)]
    line = _line(partner=9, kind="cod_remittance", on=date(2026, 10, 11), gross=0, amount=99_900)
    rows = _shortlist([line], orders)
    assert [row["order_id"] for row in rows] == ["COD"]
    assert rows[0]["due_date"] == date(2026, 10, 11)  # delivered + the courier's 10 days, not the channel's


def test_exact_awb_match_is_a_certain_candidate_and_at_most_five_are_kept():
    orders = [_order(f"O{i}") for i in range(8)] + [_order("BY-AWB", value=1, awb="AWB-1")]
    rows = _shortlist([_line(awb="AWB-1")], orders)
    assert rows[0]["order_id"] == "BY-AWB" and rows[0]["rule_score"] == 1.0 and rows[0]["awb_match"]
    assert len(rows) == 5


def test_net_only_lines_compare_with_expected_net():
    rows = _shortlist([_line(gross=0, amount=85_480)], [_order("NET", net=85_480), _order("WRONG-NET", net=95_000)])
    assert [row["order_id"] for row in rows] == ["NET"]


# ---------- confidence and how the AI's answer is used ----------

def _candidates(*scores):
    return [{"order_id": f"O{index}", "rule_score": score, "amount_diff_paise": 0, "days_from_due": 0, "awb_match": False}
            for index, score in enumerate(scores)]


def test_rule_confidence_is_never_high_for_look_alikes():
    assert rule_confidence([1.0]) == 1.0
    assert rule_confidence([1.0, 1.0]) == 0.5
    assert rule_confidence([1.0, 0.4]) == 0.8
    assert rule_confidence([]) == 0.0


def test_ai_breaks_an_exact_tie_but_cannot_make_it_look_certain():
    candidates = _candidates(1.0, 1.0)
    suggested, confidence, reason, engine, ai_pick = combine(candidates, Ranking("O1", 0.95, "Closest date."))
    assert (suggested, engine, ai_pick) == ("O1", "llm", "O1")
    assert confidence == evidence_cap(candidates, "O1") == 0.5


def test_ai_never_overrules_a_clear_rule_winner():
    candidates = _candidates(1.0, 0.7)
    suggested, confidence, reason, _, ai_pick = combine(candidates, Ranking("O1", 0.99, "Looks right."))
    assert suggested == "O0" and ai_pick == "O1"
    assert confidence <= 0.6
    assert "The AI preferred O1" in reason


def test_without_ai_the_rules_decide():
    suggested, confidence, reason, engine, ai_pick = combine(_candidates(1.0), None)
    assert (suggested, confidence, engine, ai_pick) == ("O0", 1.0, "rules", None)
    assert "only candidate" in reason


# ---------- the AI ranker and its fallback ----------

def _item():
    return RankItem(
        line_id=7,
        line={"kind": "settlement", "partner": "Marketplace 1", "line_date": "2026-10-08", "gross_rupees": 1199.0, "amount_rupees": 854.8},
        candidates=[{"order_id": "ORD-M-1", "customer_name": "Meera Iyer", "customer_phone": "9845012345", "value_rupees": 1199.0},
                    {"order_id": "ORD-M-2", "value_rupees": 1199.0}],
    )


def _gemini_reply(payload) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})
    return httpx.MockTransport(handler)


def test_no_personal_data_is_sent_to_the_ai():
    prompt = build_prompt([_item()])
    assert "Meera" not in prompt and "9845012345" not in prompt and "customer" not in prompt


def test_gemini_answer_is_used_when_valid():
    reply = {"results": [{"line_id": 7, "order_id": "ORD-M-2", "confidence": 0.8, "reason": "Paid on the due date."}]}
    ranker = GeminiRanker("key", "model", client=httpx.Client(transport=_gemini_reply(reply)))
    outcome = ranker.rank([_item()])
    assert outcome.engine == "llm"
    assert outcome.rankings[7] == Ranking("ORD-M-2", 0.8, "Paid on the due date.")


@pytest.mark.parametrize(("reply", "note"), [
    ("not json at all", AI_UNAVAILABLE),
    ({"results": [{"line_id": 7, "order_id": "ORD-INVENTED", "confidence": 0.99, "reason": "?"}]}, AI_INVALID),
    ({"results": [{"line_id": 7, "order_id": "ORD-M-1", "confidence": 3, "reason": "out of range"}]}, AI_INVALID),
])
def test_bad_ai_answers_fall_back_to_the_rules(reply, note):
    ranker = GeminiRanker("key", "model", client=httpx.Client(transport=_gemini_reply(reply)))
    outcome = ranker.rank([_item()])
    assert outcome.engine == "rules" and outcome.rankings == {} and outcome.notes[7] == note


def test_http_errors_fall_back_to_the_rules():
    transport = httpx.MockTransport(lambda request: httpx.Response(429, json={"error": "quota"}))
    outcome = GeminiRanker("key", "model", client=httpx.Client(transport=transport)).rank([_item()])
    assert outcome.notes[7] == AI_UNAVAILABLE


# ---------- end to end: queueing, suggestions, decisions ----------

def _source(db, partner: str, file_kind: str):
    source = db.scalar(select(Source).join(Partner, Partner.id == Source.partner_id).where(Partner.name == partner, Source.file_kind == file_kind))
    return source, db.scalar(select(ColumnMapping).where(ColumnMapping.source_id == source.id, ColumnMapping.is_active))


@pytest.fixture
def queued(db, finance_user, tmp_path: Path):
    seed_reference_data(db)
    seed_initial_mappings(db, created_by=finance_user.id)
    db.commit()
    data = generate(n_orders=1_500, seed=21, missing_id_share=0.03, ambiguous_pairs=1)
    write_all(data, tmp_path)
    for layout in FORMATS:
        source, mapping = _source(db, layout.partner, layout.file_kind)
        process_file(db, source, mapping, tmp_path / layout.filename, layout.filename, finance_user.id)
    run_reconciliation(db, started_by=finance_user.id, as_of=AS_OF)
    refresh_claims(db)
    refresh_suggestions(db, ranker=RuleRanker())
    db.commit()
    return data


def test_lines_without_an_order_id_are_queued_not_rejected_and_never_closed_automatically(db, queued):
    lines = list(db.scalars(select(UnmatchedLine)))
    assert len(lines) == len(queued.missing_ids) > 0
    assert all(line.status == "open" and line.resolved_order_id is None for line in lines)
    assert all(line.suggested_order_id and line.candidates_json for line in lines)
    assert any(line.confidence >= 0.9 for line in lines)
    # Even a certain-looking suggestion is not in the ledger until a person accepts it.
    references = {line.reference for line in lines}
    assert db.scalar(select(func.count()).select_from(SettlementLine).where(SettlementLine.raw_ref.in_(references))) == 0
    truth = {line["reference"]: line["order_id"] for line in queued.missing_ids}
    assert all(truth[line.reference] in [c["order_id"] for c in line.candidates_json] for line in lines)


def test_reuploading_a_file_does_not_queue_its_lines_twice(db, queued, finance_user, tmp_path):
    layout = next(layout for layout in FORMATS if layout.partner == "Marketplace 2" and layout.file_kind == "settlement")
    before = db.scalar(select(func.count()).select_from(UnmatchedLine))
    source, mapping = _source(db, layout.partner, layout.file_kind)
    upload = process_file(db, source, mapping, tmp_path / layout.filename, layout.filename, finance_user.id)
    assert upload.rows_unmatched == 0 and upload.rows_ok == 0
    assert db.scalar(select(func.count()).select_from(UnmatchedLine)) == before


def test_accept_links_the_line_rematches_only_that_order_and_is_audited(finance_client, db, queued):
    line = db.scalar(select(UnmatchedLine).where(UnmatchedLine.kind == "settlement").order_by(UnmatchedLine.confidence.desc()).limit(1))
    order_id = line.suggested_order_id
    assert db.scalar(select(ReconResult.status).where(ReconResult.order_id == order_id)) == "unpaid_past_due"
    untouched = db.scalar(select(ReconResult).where(ReconResult.order_id != order_id).limit(1))
    untouched_before = (untouched.order_id, untouched.status, untouched.received_paise)

    response = finance_client.post(f"/review-queue/{line.id}/accept", json={"order_id": order_id})
    assert response.status_code == 200, response.text
    assert response.json()["orders_rematched"] == 1

    db.expire_all()
    assert db.get(UnmatchedLine, line.id).status == "accepted"
    assert db.scalar(select(func.count()).select_from(SettlementLine).where(SettlementLine.order_id == order_id)) == 1
    result = db.scalar(select(ReconResult).where(ReconResult.order_id == order_id))
    assert result.status != "unpaid_past_due" and result.received_paise != 0
    other = db.scalar(select(ReconResult).where(ReconResult.order_id == untouched_before[0]))
    assert (other.order_id, other.status, other.received_paise) == untouched_before
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "review_line_accepted"))
    assert audit.after_json["order_id"] == order_id and audit.after_json["was_suggested"] is True
    assert finance_client.post(f"/review-queue/{line.id}/accept", json={"order_id": order_id}).status_code == 409


def test_pick_another_candidate_but_never_an_order_outside_the_shortlist(finance_client, db, queued):
    line = next(line for line in db.scalars(select(UnmatchedLine)) if len(line.candidates_json) > 1)
    other = line.candidates_json[1]["order_id"]
    assert finance_client.post(f"/review-queue/{line.id}/accept", json={"order_id": "ORD-NOT-LISTED"}).status_code == 409
    response = finance_client.post(f"/review-queue/{line.id}/accept", json={"order_id": other, "note": "Matched on the UTR"})
    assert response.status_code == 200
    db.expire_all()
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "review_line_accepted"))
    assert audit.after_json["was_suggested"] is False


def test_reject_leaves_the_line_out_of_the_ledger(finance_client, db, queued):
    line = db.scalar(select(UnmatchedLine).limit(1))
    settlements_before = db.scalar(select(func.count()).select_from(SettlementLine))
    assert finance_client.post(f"/review-queue/{line.id}/reject", json={"note": "Not ours"}).status_code == 200
    db.expire_all()
    assert db.get(UnmatchedLine, line.id).status == "rejected"
    assert db.scalar(select(func.count()).select_from(SettlementLine)) == settlements_before
    assert db.scalar(select(AuditLog.action).where(AuditLog.entity_id == str(line.id))) == "review_line_rejected"


def test_bulk_accept_takes_only_confident_lines(finance_client, db, queued):
    lines = list(db.scalars(select(UnmatchedLine)))
    confident = [line.id for line in lines if line.confidence >= 0.9]
    unsure = [line.id for line in lines if line.confidence < 0.9]
    assert confident and unsure
    response = finance_client.post("/review-queue/bulk-accept", json={"line_ids": confident + unsure[:2]})
    body = response.json()
    assert {item["line_id"] for item in body["accepted"]} <= set(confident)
    assert {item["line_id"] for item in body["skipped"]} >= set(unsure[:2])
    db.expire_all()
    assert all(db.get(UnmatchedLine, line_id).status == "open" for line_id in unsure)


def test_queue_reads_and_counts(finance_client, founder_client, db, queued):
    body = founder_client.get("/review-queue").json()
    assert body["counts"]["open"] == len(body["lines"]) == len(queued.missing_ids)
    line = body["lines"][0]
    assert line["candidates"][0]["value_paise"] and line["filename"] and line["row_number"]
    assert founder_client.get("/dashboard").json()["review_queue"]["open"] == body["counts"]["open"]


def test_cofounder_cannot_decide(founder_client, db, queued):
    line = db.scalar(select(UnmatchedLine).limit(1))
    assert founder_client.post(f"/review-queue/{line.id}/accept", json={"order_id": line.suggested_order_id}).status_code == 403
    assert founder_client.post(f"/review-queue/{line.id}/reject", json={}).status_code == 403
    assert founder_client.post("/review-queue/bulk-accept", json={"line_ids": [line.id]}).status_code == 403
    db.expire_all()
    assert db.get(UnmatchedLine, line.id).status == "open"


def test_upload_queues_lines_and_says_when_the_ai_is_not_configured(app, finance_client, db, finance_user, tmp_path):
    seed_reference_data(db)
    seed_initial_mappings(db, created_by=finance_user.id)
    db.commit()
    data = generate(n_orders=800, seed=4, missing_id_share=0.05)
    write_all(data, tmp_path)
    app.dependency_overrides[get_match_ranker] = lambda: RuleRanker(AI_NO_KEY)
    layout = format_for("Marketplace 2", "settlement")
    source, _ = _source(db, layout.partner, layout.file_kind)
    with (tmp_path / layout.filename).open("rb") as handle:
        inspected = finance_client.post("/uploads/inspect", data={"source_id": source.id}, files={"file": (layout.filename, handle, "text/csv")}).json()
    mapping_id = inspected["active_mapping"]["id"]
    processed = finance_client.post(f"/uploads/{inspected['token']}/process", json={"mapping_id": mapping_id}).json()
    expected = sum(1 for line in data.missing_ids if line["partner"] == "Marketplace 2")
    assert processed["upload"]["rows_unmatched"] == expected > 0
    assert processed["upload"]["rows_rejected"] == 0
    lines = list(db.scalars(select(UnmatchedLine)))
    assert len(lines) == expected
    assert all(line.engine == "rules" and line.ai_note == AI_NO_KEY and line.status == "open" for line in lines)
