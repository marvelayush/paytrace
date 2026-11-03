"""Allowed values for status-like columns. Kept in one place so API schemas and the DB agree."""

ROLES = ("finance_exec", "cofounder")
# `warehouse` is our own warehouse: it sends return receipt scans, never money.
PARTNER_KINDS = ("website", "marketplace", "quickcom", "courier", "warehouse")
FILE_KINDS = ("orders", "settlement", "cod_remittance", "freight_invoice", "warehouse_returns")
UPLOAD_STATUSES = ("pending", "processing", "done", "failed")
PAYMENT_MODES = ("cod", "prepaid")
FREIGHT_LEGS = ("forward", "return")
# Final courier status of an order, normalised from partner wording.
DELIVERY_STATUSES = ("delivered", "returned", "rto", "in_transit", "cancelled")
RETURNED_STATUSES = ("returned", "rto")
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
