"""Seed reference data: partners, sources and the starting rate cards.

The rate values are ASSUMPTIONS (docs/ASSUMPTIONS.md, A17), chosen to be realistic and to reproduce
the three sample orders in the brief exactly:

  ORD-W-204118  Website, ₹1,499 COD, delivered via Courier A (450 g)
      1,499 − COD fee 30 − forward freight 60 (≤500 g)           = expected 1,409
  ORD-M-88120   Marketplace 1, ₹1,199 prepaid, delivered
      1,199 − commission 20% (239.80) − fixed fee 60.20          = expected 899
      (TCS 0.5% = 6.00 and TDS 0.1% = 1.20 shown separately)
  ORD-W-204377  Website, ₹2,398 prepaid, returned via Courier B (480 g)
      −(forward 48 + return 48)                                  = expected −96
"""

from datetime import date

RATE_CARDS_EFFECTIVE_FROM = date(2026, 1, 1)

# name, kind, settlement_days (A3: days after delivery by which money is due)
PARTNERS: list[tuple[str, str, int]] = [
    ("Website", "website", 3),  # payment gateway settles prepaid orders T+3 (A3)
    ("Marketplace 1", "marketplace", 7),
    ("Marketplace 2", "marketplace", 7),
    ("Marketplace 3", "marketplace", 7),
    ("QuickCom 1", "quickcom", 7),
    ("QuickCom 2", "quickcom", 7),
    ("Courier A", "courier", 10),
    ("Courier B", "courier", 10),
    ("Warehouse", "warehouse", 0),
]

# Which reports each partner sends us.
SOURCE_KINDS_BY_PARTNER_KIND: dict[str, list[tuple[str, str]]] = {
    "website": [("orders", "order export"), ("settlement", "payment gateway settlement")],
    "marketplace": [("orders", "order report"), ("settlement", "settlement report")],
    "quickcom": [("orders", "order report"), ("settlement", "payout report")],
    "courier": [("cod_remittance", "COD remittance"), ("freight_invoice", "freight invoice")],
    "warehouse": [("warehouse_returns", "return receipt scans")],
}

# Channel rate cards. Percentages in basis points, money in paise.
CHANNEL_RATE_CARDS: dict[str, dict[str, int]] = {
    "Website": {"gateway_pct_bp": 200},
    "Marketplace 1": {"commission_pct_bp": 2000, "fixed_fee_paise": 6020, "tcs_pct_bp": 50, "tds_pct_bp": 10},
    "Marketplace 2": {"commission_pct_bp": 1800, "fixed_fee_paise": 5000, "tcs_pct_bp": 50, "tds_pct_bp": 10},
    "Marketplace 3": {"commission_pct_bp": 2200, "fixed_fee_paise": 4500, "tcs_pct_bp": 50, "tds_pct_bp": 10},
    "QuickCom 1": {"commission_pct_bp": 2500, "fixed_fee_paise": 2500, "tcs_pct_bp": 50, "tds_pct_bp": 10},
    "QuickCom 2": {"commission_pct_bp": 2400, "fixed_fee_paise": 3000, "tcs_pct_bp": 50, "tds_pct_bp": 10},
}

# Courier rate cards: COD fee and weight slabs (up_to_g, price_paise); return leg priced like forward.
_COURIER_A_SLABS = [(500, 6000), (1000, 8500), (2000, 12500), (5000, 21000), (10000, 36000)]
_COURIER_B_SLABS = [(500, 4800), (1000, 7100), (2000, 11000), (5000, 19000), (10000, 32000)]

COURIER_RATE_CARDS: dict[str, dict] = {
    "Courier A": {"cod_fee_paise": 3000, "cod_fee_pct_bp": 0, "forward": _COURIER_A_SLABS, "return": _COURIER_A_SLABS},
    "Courier B": {"cod_fee_paise": 0, "cod_fee_pct_bp": 200, "forward": _COURIER_B_SLABS, "return": _COURIER_B_SLABS},
}
