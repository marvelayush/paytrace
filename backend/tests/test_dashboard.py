"""Dashboard numbers agree with the underlying results."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import ColumnMapping, Partner, ReconResult, Source
from app.sample_data.formats import FORMATS, write_all
from app.sample_data.generator import generate
from app.services.claims import refresh_claims
from app.services.matching import FLAGGED_STATUSES, run_reconciliation
from app.services.seeding import seed_initial_mappings, seed_reference_data
from app.services.upload_processing import process_file


@pytest.fixture
def reconciled(db, finance_user, tmp_path: Path):
    seed_reference_data(db)
    seed_initial_mappings(db, created_by=finance_user.id)
    db.commit()
    write_all(generate(n_orders=1_200, seed=31), tmp_path)
    for layout in FORMATS:
        source = db.scalar(select(Source).join(Partner, Partner.id == Source.partner_id).where(Partner.name == layout.partner, Source.file_kind == layout.file_kind))
        mapping = db.scalar(select(ColumnMapping).where(ColumnMapping.source_id == source.id, ColumnMapping.is_active))
        process_file(db, source, mapping, tmp_path / layout.filename, layout.filename, finance_user.id)
    run_reconciliation(db, started_by=finance_user.id, as_of=date(2026, 11, 3))
    refresh_claims(db)
    db.commit()


def test_empty_dashboard_before_any_run(founder_client):
    assert founder_client.get("/dashboard").json() == {"run": None}


def test_matrix_adds_up_to_money_at_risk(db, founder_client, reconciled):
    data = founder_client.get("/dashboard").json()
    at_risk = db.scalar(select(func.sum(ReconResult.at_risk_paise)).where(ReconResult.status.in_(FLAGGED_STATUSES)))
    assert data["kpis"]["money_at_risk_paise"] == at_risk
    assert sum(row["at_risk_paise"] for row in data["matrix"]) == at_risk
    assert sum(total["at_risk_paise"] for total in data["bucket_totals"].values()) == at_risk
    for row in data["matrix"]:
        assert row["at_risk_paise"] == sum(cell["at_risk_paise"] for cell in row["buckets"].values())
    assert [row["at_risk_paise"] for row in data["matrix"]] == sorted((row["at_risk_paise"] for row in data["matrix"]), reverse=True)


def test_tax_is_reported_separately_from_risk(db, founder_client, reconciled):
    data = founder_client.get("/dashboard").json()
    assert data["kpis"]["tcs_paise"] == db.scalar(select(func.sum(ReconResult.tcs_paise)))
    assert data["kpis"]["tds_paise"] > 0
    assert sum(row["tcs_paise"] for row in data["tax_by_partner"]) == data["kpis"]["tcs_paise"]


def test_claims_and_run_information(founder_client, reconciled):
    data = founder_client.get("/dashboard").json()
    assert data["kpis"]["open_claims"]["total_paise"] == data["kpis"]["money_at_risk_paise"]
    assert data["run"]["order_count"] == 1_200
    assert data["run"]["auto_matched_pct"] >= 98
    assert data["run"]["duration_ms"] > 0
