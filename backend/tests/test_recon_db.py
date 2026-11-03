"""Reconciliation through the database: files -> upload pipeline -> engine -> COPY results."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import ColumnMapping, Partner, ReconResult, ReconRun, Source
from app.sample_data.formats import FORMATS, write_all
from app.sample_data.generator import generate
from app.services.matching import run_reconciliation
from app.services.seeding import seed_initial_mappings, seed_reference_data
from app.services.upload_processing import process_file


@pytest.fixture
def loaded(db, finance_user, tmp_path: Path):
    """A small generated month, written in every partner's layout and processed like real uploads."""
    seed_reference_data(db)
    seed_initial_mappings(db, created_by=finance_user.id)
    db.commit()
    write_all(generate(n_orders=1_500, seed=5), tmp_path)
    for layout in FORMATS:
        source = db.scalar(
            select(Source).join(Partner, Partner.id == Source.partner_id).where(Partner.name == layout.partner, Source.file_kind == layout.file_kind)
        )
        mapping = db.scalar(select(ColumnMapping).where(ColumnMapping.source_id == source.id, ColumnMapping.is_active))
        upload = process_file(db, source, mapping, tmp_path / layout.filename, layout.filename, finance_user.id)
        assert upload.status == "done" and upload.rows_rejected == 0, layout.filename
    return finance_user


def test_run_writes_one_result_per_order_with_brief_values(db, loaded):
    summary = run_reconciliation(db, started_by=loaded.id, as_of=date(2026, 11, 3))
    db.commit()

    assert summary.order_count == 1_500
    assert db.scalar(select(func.count()).select_from(ReconResult)) == 1_500
    assert set(summary.stage_ms) == {"load", "match", "write"}

    marketplace = db.scalar(select(ReconResult).where(ReconResult.order_id == "ORD-M-88120"))
    assert (marketplace.expected_paise, marketplace.received_paise, marketplace.diff_paise, marketplace.status) == (89_900, 86_200, -3_700, "short_paid")
    assert marketplace.expected_breakdown_json["commission"] == 23_980
    assert marketplace.evidence_json["settlement_lines"] == 1

    cod = db.scalar(select(ReconResult).where(ReconResult.order_id == "ORD-W-204118"))
    assert (cod.expected_paise, cod.received_paise, cod.status) == (140_900, 0, "unpaid_past_due")

    returned = db.scalar(select(ReconResult).where(ReconResult.order_id == "ORD-W-204377"))
    assert (returned.expected_paise, returned.received_paise, returned.diff_paise, returned.status) == (-9_600, -14_200, -4_600, "freight_overcharged")


def test_a_new_run_replaces_results_but_keeps_run_history(db, loaded):
    first = run_reconciliation(db, started_by=loaded.id)
    second = run_reconciliation(db, started_by=loaded.id)
    db.commit()
    assert second.run_id != first.run_id
    assert db.scalar(select(func.count()).select_from(ReconRun)) == 2
    assert set(db.scalars(select(ReconResult.run_id).distinct())) == {second.run_id}


def test_api_run_and_latest(finance_client, founder_client, db, loaded):
    assert founder_client.get("/recon/runs/latest").json() is None
    started = finance_client.post("/recon/runs")
    assert started.status_code == 201
    latest = founder_client.get("/recon/runs/latest").json()
    assert latest["run_id"] == started.json()["run_id"]
    assert latest["order_count"] == 1_500
    assert latest["auto_matched_pct"] >= 98
    assert founder_client.post("/recon/runs").status_code == 403


def test_processing_an_upload_reruns_reconciliation(finance_client, db, loaded, tmp_path):
    source = db.scalar(select(Source).join(Partner, Partner.id == Source.partner_id).where(Partner.name == "QuickCom 2", Source.file_kind == "settlement"))
    content = b"Payout Date,Order No.,Bill Amount,Commission,Platform Charges,TCS u/s 52,TDS u/s 194-O,Net Payable,Payout ID\n01/11/2026,ORD-R-70001,10.00,0,0,0,0,10.00,EXTRA-1\n"
    inspected = finance_client.post("/uploads/inspect", data={"source_id": str(source.id)}, files={"file": ("extra.csv", content, "text/csv")}).json()
    processed = finance_client.post(f"/uploads/{inspected['token']}/process", json={"mapping_id": inspected["active_mapping"]["id"]}).json()
    assert processed["reconciliation"]["order_count"] == 1_500
