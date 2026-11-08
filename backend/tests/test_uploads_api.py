"""Upload flow end to end: inspect -> (review -> approve) -> process, versions and rollback, rejected rows."""

import io
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models import AuditLog, ColumnMapping, Order, Partner, SettlementLine, Source, UnmatchedLine, UploadRowError
from app.sample_data.formats import FORMAT_CHANGED, FORMATS
from app.services.seeding import seed_initial_mappings, seed_reference_data

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample_data"


@pytest.fixture
def seeded(db, finance_user):
    seed_reference_data(db)
    seed_initial_mappings(db, created_by=finance_user.id)
    db.commit()


def source_id(db, partner: str, file_kind: str) -> int:
    return db.scalar(
        select(Source.id).join(Partner, Partner.id == Source.partner_id).where(Partner.name == partner, Source.file_kind == file_kind)
    )


def inspect(client, source: int, name: str, content: bytes):
    return client.post("/uploads/inspect", data={"source_id": str(source)}, files={"file": (name, io.BytesIO(content), "text/csv")})


def sample_bytes(filename: str, folder: Path = SAMPLE_DIR) -> bytes:
    return (folder / filename).read_bytes()


def test_known_layout_is_reused_and_processed(finance_client, db, seeded):
    source = source_id(db, "Marketplace 2", "settlement")
    inspected = inspect(finance_client, source, "marketplace2_settlement.csv", sample_bytes("marketplace2_settlement.csv"))
    assert inspected.status_code == 200
    body = inspected.json()
    assert body["decision"] == "reuse"
    assert body["active_mapping"]["version"] == 1
    assert body["suggestion"]["engine"] == "saved"
    assert len(body["preview"]["rows"]) == 20
    assert body["preview"]["rows_with_errors"] == 0

    processed = finance_client.post(f"/uploads/{body['token']}/process", json={"mapping_id": body["active_mapping"]["id"]})
    assert processed.status_code == 200
    upload = processed.json()["upload"]
    lines_in_file = sample_bytes("marketplace2_settlement.csv").decode().count("\n") - 1
    # A few lines carry no order ID: they wait in the review queue instead of being saved or rejected.
    assert (upload["status"], upload["rows_rejected"]) == ("done", 0)
    assert upload["rows_unmatched"] > 0
    assert upload["rows_ok"] + upload["rows_unmatched"] == lines_in_file
    assert db.scalar(select(func.count()).select_from(SettlementLine)) == upload["rows_ok"]
    assert db.scalar(select(func.count()).select_from(UnmatchedLine)) == upload["rows_unmatched"]


def test_uploading_the_same_report_twice_does_not_double_count(finance_client, db, seeded):
    source = source_id(db, "QuickCom 2", "settlement")
    content = sample_bytes("quickcom2_payouts.csv")
    for _ in range(2):
        body = inspect(finance_client, source, "quickcom2_payouts.csv", content).json()
        result = finance_client.post(f"/uploads/{body['token']}/process", json={"mapping_id": body["active_mapping"]["id"]}).json()
    lines = content.decode().count("\n") - 1
    assert (result["upload"]["rows_ok"], result["upload"]["rows_unmatched"], result["upload"]["rows_duplicate"]) == (0, 0, lines)
    queued = db.scalar(select(func.count()).select_from(UnmatchedLine))
    assert db.scalar(select(func.count()).select_from(SettlementLine)) + queued == lines


def test_changed_layout_needs_review_then_approval_creates_version_2(finance_client, db, seeded):
    source = source_id(db, "Marketplace 1", "settlement")
    content = sample_bytes(FORMAT_CHANGED.filename, SAMPLE_DIR / "format_changed")
    body = inspect(finance_client, source, FORMAT_CHANGED.filename, content).json()

    assert body["decision"] == "review"
    assert body["suggestion"] == {"engine": "fuzzy", "notice": "AI unavailable, showing best guesses"}
    proposed = {field["name"]: field["source_column"] for field in body["preview"]["fields"]}
    assert proposed == {name: FORMAT_CHANGED.mapping()["columns"].get(name) for name in proposed}

    approved = finance_client.post(f"/sources/{source}/mappings", json={"token": body["token"], "columns": proposed, "notes": "Partner renamed columns"})
    assert approved.status_code == 201
    mapping = approved.json()
    assert (mapping["version"], mapping["is_active"], mapping["engine"]) == (2, True, "fuzzy")

    processed = finance_client.post(f"/uploads/{body['token']}/process", json={"mapping_id": mapping["id"]}).json()
    assert processed["upload"]["rows_rejected"] == 0
    assert processed["upload"]["mapping_version"] == 2

    versions = finance_client.get(f"/sources/{source}/mappings").json()
    assert [(v["version"], v["is_active"]) for v in versions] == [(2, True), (1, False)]
    assert db.scalar(select(AuditLog).where(AuditLog.action == "mapping.approve")).before_json["version"] == 1


def test_rollback_restores_the_previous_version(finance_client, db, seeded):
    source = source_id(db, "Marketplace 1", "settlement")
    body = inspect(finance_client, source, "new.csv", sample_bytes(FORMAT_CHANGED.filename, SAMPLE_DIR / "format_changed")).json()
    columns = {field["name"]: field["source_column"] for field in body["preview"]["fields"]}
    finance_client.post(f"/sources/{source}/mappings", json={"token": body["token"], "columns": columns})
    version_1 = db.scalar(select(ColumnMapping).where(ColumnMapping.source_id == source, ColumnMapping.version == 1))

    rolled_back = finance_client.post(f"/sources/{source}/mappings/{version_1.id}/rollback")
    assert rolled_back.status_code == 200
    assert [(v["version"], v["is_active"]) for v in finance_client.get(f"/sources/{source}/mappings").json()] == [(2, False), (1, True)]
    assert db.scalar(select(AuditLog).where(AuditLog.action == "mapping.rollback")).after_json["version"] == 1

    # The original Excel layout is recognised again by its fingerprint.
    again = inspect(finance_client, source, "marketplace1_settlement.xlsx", sample_bytes("marketplace1_settlement.xlsx"))
    assert again.json()["decision"] == "reuse"


def test_a_layout_matching_an_older_version_is_proposed_from_that_version(finance_client, db, seeded):
    source = source_id(db, "Marketplace 1", "settlement")
    body = inspect(finance_client, source, "new.csv", sample_bytes(FORMAT_CHANGED.filename, SAMPLE_DIR / "format_changed")).json()
    columns = {field["name"]: field["source_column"] for field in body["preview"]["fields"]}
    finance_client.post(f"/sources/{source}/mappings", json={"token": body["token"], "columns": columns})

    old_layout = inspect(finance_client, source, "m1.xlsx", sample_bytes("marketplace1_settlement.xlsx")).json()
    assert (old_layout["decision"], old_layout["matched_version"], old_layout["suggestion"]["engine"]) == ("review", 1, "saved")


def test_preview_flags_a_wrong_column_choice(finance_client, db, seeded):
    source = source_id(db, "Marketplace 1", "settlement")
    body = inspect(finance_client, source, "new.csv", sample_bytes(FORMAT_CHANGED.filename, SAMPLE_DIR / "format_changed")).json()
    columns = {field["name"]: field["source_column"] for field in body["preview"]["fields"]}
    columns["settlement_date"] = "Order Reference"  # a user mistake: not dates

    preview = finance_client.post(f"/sources/{source}/mappings/preview", json={"token": body["token"], "columns": columns}).json()
    date_field = next(field for field in preview["fields"] if field["name"] == "settlement_date")
    assert date_field["error_count"] == 20
    assert date_field["needs_confirmation"] is True
    assert "is not a date" in preview["rows"][0]["errors"]["settlement_date"]


def test_approving_without_required_fields_is_refused(finance_client, db, seeded):
    source = source_id(db, "Marketplace 1", "settlement")
    body = inspect(finance_client, source, "new.csv", sample_bytes(FORMAT_CHANGED.filename, SAMPLE_DIR / "format_changed")).json()
    response = finance_client.post(f"/sources/{source}/mappings", json={"token": body["token"], "columns": {"order_id": "Order Reference"}})
    assert response.status_code == 422
    assert "Settlement date" in response.json()["detail"]


def test_approving_a_column_that_is_not_in_the_file_is_refused(finance_client, db, seeded):
    source = source_id(db, "Marketplace 1", "settlement")
    body = inspect(finance_client, source, "new.csv", sample_bytes(FORMAT_CHANGED.filename, SAMPLE_DIR / "format_changed")).json()
    columns = {field["name"]: field["source_column"] for field in body["preview"]["fields"]}
    columns["net"] = "Invented"
    assert finance_client.post(f"/sources/{source}/mappings", json={"token": body["token"], "columns": columns}).status_code == 422


def test_rejected_rows_are_kept_and_exported_safely(finance_client, db, seeded):
    source = source_id(db, "QuickCom 1", "settlement")
    content = (
        "payout_date,order_id,gross_sales,platform_fee,other_charges,tcs,tds,payout_amount,payout_ref\n"
        "2026-10-01,ORD-Q-1,100.00,25.00,25.00,0.50,0.10,49.40,P1\n"
        "not-a-date,ORD-Q-2,100.00,25.00,25.00,0.50,0.10,49.40,P2\n"
        "2026-10-01,ORD-Q-3,100.00,25.00,25.00,0.50,0.10,=HYPERLINK(1),P3\n"
    ).encode()
    body = inspect(finance_client, source, "quickcom1_payouts.csv", content).json()
    upload = finance_client.post(f"/uploads/{body['token']}/process", json={"mapping_id": body["active_mapping"]["id"]}).json()["upload"]
    assert (upload["rows_ok"], upload["rows_rejected"]) == (1, 2)

    errors = finance_client.get(f"/uploads/{upload['id']}/errors").json()
    assert [error["row_number"] for error in errors] == [2, 3]
    assert "Settlement date: 'not-a-date' is not a date" in errors[0]["reason"]

    exported = finance_client.get(f"/uploads/{upload['id']}/errors.csv")
    assert exported.headers["content-type"].startswith("text/csv")
    assert "=HYPERLINK" not in exported.text.replace("'=HYPERLINK", "")  # only the defused form appears
    assert db.scalar(select(func.count()).select_from(UploadRowError)) == 2


def test_customer_personal_data_is_masked_when_stored(finance_client, db, seeded):
    source = source_id(db, "Website", "orders")
    body = inspect(finance_client, source, "website_orders.csv", sample_bytes("website_orders.csv")).json()
    finance_client.post(f"/uploads/{body['token']}/process", json={"mapping_id": body["active_mapping"]["id"]})

    order = db.get(Order, "ORD-W-204118")
    assert (order.customer_name_masked, order.customer_phone_masked, order.pincode) == ("M***r", "98******45", "560034")
    assert (order.value_paise, order.payment_mode, order.delivery_status, order.dead_weight_g) == (149_900, "cod", "delivered", 450)
    assert order.courier_partner_id == db.scalar(select(Partner.id).where(Partner.name == "Courier A"))
    # And the preview shown in the browser was masked too.
    first_row = body["preview"]["rows"][0]
    assert first_row["values"]["customer_phone"].count("*") == 6


def test_unsupported_and_empty_files_are_refused(finance_client, db, seeded):
    source = source_id(db, "Website", "orders")
    assert inspect(finance_client, source, "report.pdf", b"%PDF-1.4").status_code == 422
    assert inspect(finance_client, source, "empty.csv", b"").status_code == 422
    assert inspect(finance_client, source, "headers.csv", b"a,b\n").status_code == 422


def test_expired_or_unknown_token_is_404(finance_client, db, seeded):
    assert finance_client.post("/uploads/not-a-real-token/process", json={"mapping_id": 1}).status_code == 404


def test_cofounder_can_see_history_but_not_upload(founder_client, db, seeded):
    source = source_id(db, "Website", "orders")
    assert founder_client.get("/uploads").status_code == 200
    assert founder_client.get("/sources").status_code == 200
    assert inspect(founder_client, source, "website_orders.csv", b"x").status_code == 403


@pytest.mark.parametrize("layout", FORMATS, ids=lambda layout: layout.filename)
def test_every_sample_file_processes_without_rejections(finance_client, db, seeded, layout):
    source = source_id(db, layout.partner, layout.file_kind)
    body = inspect(finance_client, source, layout.filename, sample_bytes(layout.filename)).json()
    assert body["decision"] == "reuse"
    upload = finance_client.post(f"/uploads/{body['token']}/process", json={"mapping_id": body["active_mapping"]["id"]}).json()["upload"]
    assert upload["status"] == "done"
    assert upload["rows_rejected"] == 0
    assert upload["rows_ok"] + upload["rows_unmatched"] == upload["row_count"] > 0
