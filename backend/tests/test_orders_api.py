"""Orders list and order detail, read from the seeded sample month."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import ColumnMapping, Partner, Source
from app.sample_data.formats import FORMATS, write_all
from app.sample_data.generator import generate
from app.services.matching import run_reconciliation
from app.services.seeding import seed_initial_mappings, seed_reference_data
from app.services.upload_processing import process_file


@pytest.fixture
def reconciled(db, finance_user, tmp_path: Path):
    seed_reference_data(db)
    seed_initial_mappings(db, created_by=finance_user.id)
    db.commit()
    write_all(generate(n_orders=1_200, seed=9), tmp_path)
    for layout in FORMATS:
        source = db.scalar(select(Source).join(Partner, Partner.id == Source.partner_id).where(Partner.name == layout.partner, Source.file_kind == layout.file_kind))
        mapping = db.scalar(select(ColumnMapping).where(ColumnMapping.source_id == source.id, ColumnMapping.is_active))
        process_file(db, source, mapping, tmp_path / layout.filename, layout.filename, finance_user.id)
    run_reconciliation(db, started_by=finance_user.id, as_of=date(2026, 11, 3))
    db.commit()


def test_list_is_sorted_by_money_at_risk_with_totals(founder_client, reconciled):
    page = founder_client.get("/recon/orders?limit=50").json()
    assert page["total"] == 1_200
    at_risk = [item["at_risk_paise"] for item in page["items"]]
    assert at_risk == sorted(at_risk, reverse=True)
    assert len(page["items"]) == 50


def test_flagged_filter_and_age_bucket(founder_client, reconciled):
    flagged = founder_client.get("/recon/orders?status=flagged&limit=500").json()
    assert flagged["total"] > 0
    assert {item["status"] for item in flagged["items"]} <= {"short_paid", "unpaid_past_due", "freight_overcharged", "return_not_received"}
    assert flagged["totals"]["at_risk_paise"] > 0

    bucket = founder_client.get("/recon/orders?age_bucket=16-30&limit=500").json()
    assert all(item["age_bucket"] == "16-30" for item in bucket["items"])


def test_partner_filter_and_search(founder_client, db, reconciled):
    marketplace = db.scalar(select(Partner.id).where(Partner.name == "Marketplace 1"))
    page = founder_client.get(f"/recon/orders?partner_id={marketplace}&limit=500").json()
    assert page["items"] and all(item["partner_name"] == "Marketplace 1" for item in page["items"])

    found = founder_client.get("/recon/orders?q=88120").json()
    assert [item["order_id"] for item in found["items"]] == ["ORD-M-88120"]


def test_unknown_status_filter_is_rejected(founder_client, reconciled):
    assert founder_client.get("/recon/orders?status=lost").status_code == 422


def test_order_detail_shows_breakdown_and_evidence(founder_client, reconciled):
    detail = founder_client.get("/recon/orders/ORD-M-88120").json()
    assert detail["result"]["status"] == "short_paid"
    assert detail["result"]["breakdown"]["commission"] == 23_980
    assert (detail["result"]["tcs_paise"], detail["result"]["tds_paise"]) == (600, 120)
    [line] = detail["evidence"]["settlement_lines"]
    assert (line["file"], line["fees_paise"], line["net_paise"]) == ("marketplace1_settlement.xlsx", 9_720, 85_480)
    assert line["row"] > 0


def test_awb_only_freight_lines_are_shown_as_evidence(founder_client, reconciled):
    detail = founder_client.get("/recon/orders/ORD-W-204377").json()
    legs = sorted((line["leg"], line["freight_paise"], line["matched_by"]) for line in detail["evidence"]["freight_lines"])
    assert legs == [("forward", 7_100, "AWB"), ("return", 7_100, "AWB")]
    assert detail["evidence"]["warehouse_receipts"]
    assert detail["order"]["customer_name"] == "R***s"  # masked


def test_unknown_order_is_404(founder_client, reconciled):
    assert founder_client.get("/recon/orders/NOPE-1").status_code == 404
