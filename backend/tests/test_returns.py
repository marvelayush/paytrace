"""Returns tracker: scan status rules, agreement with matching, warehouse scans, manual receipts, access."""

import csv
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import AuditLog, ClaimItem, ColumnMapping, ManualReturnReceipt, Partner, ReconResult, Source
from app.sample_data.formats import FORMATS, format_for, write_all
from app.sample_data.generator import generate
from app.services.claims import refresh_claims
from app.services.matching import run_reconciliation
from app.services.returns import age_bucket, scan_status
from app.services.seeding import seed_initial_mappings, seed_reference_data
from app.services.upload_processing import process_file

AS_OF = date(2026, 11, 3)


def test_scan_status_window_boundary():
    returned = date(2026, 10, 1)
    assert scan_status(returned, None, date(2026, 10, 8), window_days=7) == "waiting"  # day 7: still inside
    assert scan_status(returned, None, date(2026, 10, 9), window_days=7) == "overdue"  # day 8: overdue
    assert scan_status(returned, date(2026, 10, 20), date(2026, 10, 30), window_days=7) == "received"  # late scan still counts


@pytest.mark.parametrize(("days", "bucket"), [(0, "0-7"), (7, "0-7"), (8, "8-15"), (15, "8-15"), (16, "16-30"), (30, "16-30"), (31, "30+")])
def test_age_buckets(days, bucket):
    assert age_bucket(days) == bucket


def _source(db, partner: str, file_kind: str) -> tuple[Source, ColumnMapping]:
    source = db.scalar(select(Source).join(Partner, Partner.id == Source.partner_id).where(Partner.name == partner, Source.file_kind == file_kind))
    mapping = db.scalar(select(ColumnMapping).where(ColumnMapping.source_id == source.id, ColumnMapping.is_active))
    return source, mapping


@pytest.fixture
def reconciled(db, finance_user, tmp_path: Path):
    seed_reference_data(db)
    seed_initial_mappings(db, created_by=finance_user.id)
    db.commit()
    write_all(generate(n_orders=1_500, seed=21), tmp_path)
    for layout in FORMATS:
        source, mapping = _source(db, layout.partner, layout.file_kind)
        process_file(db, source, mapping, tmp_path / layout.filename, layout.filename, finance_user.id)
    run_reconciliation(db, started_by=finance_user.id, as_of=AS_OF)
    refresh_claims(db)
    db.commit()


def test_overdue_returns_are_exactly_the_return_not_received_results(finance_client, db, reconciled):
    body = finance_client.get("/returns", params={"status": "overdue", "limit": 500}).json()
    flagged = set(db.scalars(select(ReconResult.order_id).where(ReconResult.status == "return_not_received")))
    assert body["total"] == len(flagged) > 0
    assert {row["order_id"] for row in body["rows"]} == flagged
    assert all(row["at_risk_paise"] == row["value_paise"] for row in body["rows"])
    assert all(row["claim_id"] is not None for row in body["rows"])  # overdue returns are claimed


def test_counts_and_filters_agree(finance_client, reconciled):
    everything = finance_client.get("/returns", params={"limit": 500}).json()
    statuses = everything["counts"]["status"]
    assert sum(statuses.values()) == everything["total"]
    assert {key: value["orders"] for key, value in everything["summary"].items()} == statuses
    for courier in everything["couriers"]:
        filtered = finance_client.get("/returns", params={"courier": courier["key"]}).json()
        assert filtered["total"] == everything["counts"]["courier"][courier["key"]]
    # A chip's count is what clicking it gives, with the other filters kept.
    combo = finance_client.get("/returns", params={"status": "received", "age": "16-30"}).json()
    assert combo["total"] == combo["counts"]["status"]["received"] == combo["counts"]["age"]["16-30"]
    # Overdue first, oldest first.
    first = everything["rows"][0]
    assert first["status"] == "overdue"


def test_a_warehouse_scan_upload_moves_a_return_to_received(finance_client, db, reconciled, tmp_path: Path):
    overdue = finance_client.get("/returns", params={"status": "overdue"}).json()["rows"][0]
    layout = format_for("Warehouse", "warehouse_returns")
    path = tmp_path / "late_scan.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(layout.headers)
        row = {"order_id": overdue["order_id"], "awb": overdue["awb"] or "", "received_at": AS_OF.strftime(layout.datetime_format.split(" ")[0]) + " 10:00"}
        writer.writerow([row.get(canonical, "") if canonical else "Good" for canonical, _ in layout.columns])
    source, mapping = _source(db, "Warehouse", "warehouse_returns")
    upload = process_file(db, source, mapping, path, path.name, None)
    assert upload.rows_ok == 1
    run_reconciliation(db, started_by=None, as_of=AS_OF)
    refresh_claims(db)
    db.commit()
    after = finance_client.get("/returns", params={"q": overdue["order_id"]}).json()["rows"][0]
    assert (after["status"], after["received_how"]) == ("received", "scan")
    assert db.scalar(select(ReconResult.status).where(ReconResult.order_id == overdue["order_id"])) != "return_not_received"


def test_manual_receipt_clears_the_flag_and_the_claim_and_is_audited(finance_client, db, reconciled):
    overdue = finance_client.get("/returns", params={"status": "overdue"}).json()["rows"][0]
    order_id = overdue["order_id"]
    assert db.scalar(select(func.count()).select_from(ClaimItem).where(ClaimItem.order_id == order_id)) == 1

    response = finance_client.post(f"/returns/{order_id}/manual-receipt", json={"note": "Found in bay 4 without a label"})
    assert response.status_code == 200, response.text

    db.expire_all()
    row = finance_client.get("/returns", params={"q": order_id}).json()["rows"][0]
    assert (row["status"], row["received_how"], row["manual_note"]) == ("received", "manual", "Found in bay 4 without a label")
    assert db.scalar(select(ReconResult.status).where(ReconResult.order_id == order_id)) != "return_not_received"
    assert db.scalar(select(func.count()).select_from(ClaimItem).where(ClaimItem.order_id == order_id)) == 0
    audit = db.scalar(select(AuditLog).where(AuditLog.action == "return_marked_received", AuditLog.entity_id == order_id))
    assert audit.after_json["how"] == "manual" and audit.before_json["scan_status"] == "overdue"

    again = finance_client.post(f"/returns/{order_id}/manual-receipt", json={"note": "twice"})
    assert again.status_code == 409


def test_manual_receipt_validation(finance_client, db, reconciled):
    delivered = db.scalar(select(ReconResult.order_id).where(ReconResult.status == "settled").limit(1))
    assert finance_client.post(f"/returns/{delivered}/manual-receipt", json={"note": "not a return"}).status_code == 409
    assert finance_client.post("/returns/ORD-X-1/manual-receipt", json={"note": "unknown"}).status_code == 404
    overdue = finance_client.get("/returns", params={"status": "overdue"}).json()["rows"][0]
    assert finance_client.post(f"/returns/{overdue['order_id']}/manual-receipt", json={"note": "x"}).status_code == 422  # note too short
    before_return = {"note": "date check", "received_on": "2020-01-01"}
    assert finance_client.post(f"/returns/{overdue['order_id']}/manual-receipt", json=before_return).status_code == 409


def test_cofounder_reads_the_tracker_but_cannot_mark_received(founder_client, db, reconciled):
    body = founder_client.get("/returns").json()
    assert body["total"] > 0
    assert founder_client.get("/returns/summary").status_code == 200
    order_id = next(row["order_id"] for row in body["rows"] if row["status"] == "overdue")
    assert founder_client.post(f"/returns/{order_id}/manual-receipt", json={"note": "should be refused"}).status_code == 403
    assert db.scalar(select(func.count()).select_from(ManualReturnReceipt)) == 0


def test_dashboard_carries_the_returns_summary(finance_client, reconciled):
    dashboard = finance_client.get("/dashboard").json()
    tracker = finance_client.get("/returns").json()
    assert dashboard["returns"]["overdue"] == tracker["summary"]["overdue"]
