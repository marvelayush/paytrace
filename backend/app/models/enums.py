"""Allowed values for status-like columns. Kept in one place so API schemas and the DB agree."""

ROLES = ("finance_exec", "cofounder")
PARTNER_KINDS = ("website", "marketplace", "quickcom", "courier")
FILE_KINDS = ("orders", "settlement", "cod_remittance", "freight_invoice", "warehouse_returns")
UPLOAD_STATUSES = ("pending", "processing", "done", "failed")
PAYMENT_MODES = ("cod", "prepaid")
FREIGHT_LEGS = ("forward", "return")
# The five statuses from the brief, plus `pending` (A11: not yet due, so not money at risk).
RECON_STATUSES = (
    "settled",
    "short_paid",
    "unpaid_past_due",
    "freight_overcharged",
    "return_not_received",
    "pending",
)
CLAIM_STATUSES = ("open", "filed", "recovered", "rejected")
