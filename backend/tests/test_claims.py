"""Claims: created from flagged results by partner, kept in step, frozen once filed, exported safely."""

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.models import AuditLog, Claim, ClaimItem, ColumnMapping, Partner, ReconResult, Source
from app.sample_data.formats import FORMATS, write_all
from app.sample_data.generator import generate
from app.services.claims import refresh_claims
from app.services.evidence_export import rupees
from app.services.matching import FLAGGED_STATUSES, run_reconciliation
from app.services.seeding import seed_initial_mappings, seed_reference_data
from app.services.upload_processing import process_file


@pytest.fixture
def claimed(db, finance_user, tmp_path: Path):
    seed_reference_data(db)
    seed_initial_mappings(db, created_by=finance_user.id)
    db.commit()
    write_all(generate(n_orders=1_500, seed=21), tmp_path)
    for layout in FORMATS:
        source = db.scalar(
            select(Source).join(Partner, Partner.id == Source.partner_id).where(Partner.name == layout.partner, Source.file_kind == layout.file_kind)
        )
        mapping = db.scalar(select(ColumnMapping).where(ColumnMapping.source_id == source.id, ColumnMapping.is_active))
        process_file(db, source, mapping, tmp_path / layout.filename, layout.filename, finance_user.id)
    run_reconciliation(db, started_by=finance_user.id, as_of=date(2026, 11, 3))
    refresh_claims(db)
    db.commit()


def _partner_claim(db, name: str) -> Claim:
    partner_id = db.scalar(select(Partner.id).where(Partner.name == name))
    return db.scalar(select(Claim).where(Claim.partner_id == partner_id))


def test_every_flagged_order_lands_in_its_partners_open_claim(db, claimed):
    flagged = db.scalar(select(func.count()).select_from(ReconResult).where(ReconResult.status.in_(FLAGGED_STATUSES)))
    assert db.scalar(select(func.count()).select_from(ClaimItem)) == flagged
    mismatched = db.execute(text(
        "SELECT count(*) FROM claim_items ci JOIN claims c ON c.id = ci.claim_id JOIN recon_results r ON r.order_id = ci.order_id "
        "WHERE r.partner_id <> c.partner_id OR ci.amount_paise <> r.at_risk_paise"
    )).scalar()
    assert mismatched == 0
    for claim in db.scalars(select(Claim)):
        assert claim.status == "open"
        assert claim.total_paise == db.scalar(select(func.sum(ClaimItem.amount_paise)).where(ClaimItem.claim_id == claim.id))


def test_refresh_is_idempotent(db, claimed):
    before = db.scalar(select(func.count()).select_from(ClaimItem))
    changes = refresh_claims(db)
    db.commit()
    assert (changes["added"], changes["removed"], changes["claims_opened"]) == (0, 0, 0)
    assert db.scalar(select(func.count()).select_from(ClaimItem)) == before


def test_paid_orders_leave_open_claims_but_filed_claims_are_frozen(db, finance_client, claimed):
    m1_claim = _partner_claim(db, "Marketplace 1")
    filed = finance_client.patch(f"/claims/{m1_claim.id}", json={"status": "filed", "reference": "M1-TICKET-77"}).json()
    assert (filed["status"], filed["reference"]) == ("filed", "M1-TICKET-77")

    # Every order gets paid: open claims empty out, the filed claim keeps its evidence.
    db.execute(text("UPDATE recon_results SET status = 'settled', at_risk_paise = 0"))
    refresh_claims(db)
    db.commit()
    assert [claim.id for claim in db.scalars(select(Claim))] == [m1_claim.id]
    assert db.scalar(select(func.count()).select_from(ClaimItem).where(ClaimItem.claim_id == m1_claim.id)) == filed["item_count"]


def test_newly_flagged_orders_after_filing_open_a_new_claim(db, finance_client, claimed):
    m1_claim = _partner_claim(db, "Marketplace 1")
    finance_client.patch(f"/claims/{m1_claim.id}", json={"status": "filed"})
    clean_order = db.scalar(
        select(ReconResult.order_id).where(ReconResult.partner_id == m1_claim.partner_id, ReconResult.status == "settled").limit(1)
    )
    db.execute(text("UPDATE recon_results SET status = 'short_paid', at_risk_paise = 5000 WHERE order_id = :id"), {"id": clean_order})
    refresh_claims(db)
    db.commit()
    open_claim = db.scalar(select(Claim).where(Claim.partner_id == m1_claim.partner_id, Claim.status == "open"))
    assert open_claim is not None and open_claim.total_paise == 5000


def test_status_flow_and_audit(db, finance_client, claimed):
    claim_id = db.scalar(select(Claim.id).limit(1))
    assert finance_client.patch(f"/claims/{claim_id}", json={"status": "recovered"}).status_code == 409  # must be filed first
    assert finance_client.patch(f"/claims/{claim_id}", json={"status": "filed"}).status_code == 200
    assert finance_client.patch(f"/claims/{claim_id}", json={"status": "recovered"}).status_code == 200
    assert finance_client.patch(f"/claims/{claim_id}", json={"status": "rejected"}).status_code == 409  # closed
    actions = list(db.scalars(select(AuditLog.action).where(AuditLog.entity == "claim").order_by(AuditLog.id)))
    assert actions == ["claim.filed", "claim.recovered"]


def test_cofounder_reads_and_exports_but_cannot_change_status(db, founder_client, claimed):
    claim_id = db.scalar(select(Claim.id).limit(1))
    assert founder_client.get("/claims").status_code == 200
    assert founder_client.get(f"/claims/{claim_id}").status_code == 200
    assert founder_client.get(f"/claims/{claim_id}/evidence.csv").status_code == 200
    assert founder_client.patch(f"/claims/{claim_id}", json={"status": "filed"}).status_code == 403


def test_claim_list_is_grouped_by_partner_with_reasons(founder_client, claimed):
    claims = founder_client.get("/claims").json()
    assert len({claim["partner_name"] for claim in claims}) == len(claims)
    first = claims[0]
    assert first["item_count"] == sum(reason["count"] for reason in first["by_reason"].values())
    assert first["total_paise"] == sum(reason["amount_paise"] for reason in first["by_reason"].values())


def test_evidence_csv_lists_source_rows(db, founder_client, claimed):
    claim_id = _partner_claim(db, "Marketplace 1").id
    response = founder_client.get(f"/claims/{claim_id}/evidence.csv")
    assert response.headers["content-disposition"].endswith('marketplace-1-evidence.csv"')
    line = next(row for row in response.text.splitlines() if "ORD-M-88120" in row)
    assert "Short paid" in line and "37.00" in line and "marketplace1_settlement.xlsx row" in line


def test_evidence_pdf_is_a_pdf(db, founder_client, claimed):
    claim_id = db.scalar(select(Claim.id).limit(1))
    response = founder_client.get(f"/claims/{claim_id}/evidence.pdf")
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_indian_rupee_formatting_for_pdf():
    assert rupees(12_345_670) == "Rs 1,23,456.70"
    assert rupees(-3_700) == "-Rs 37.00"
