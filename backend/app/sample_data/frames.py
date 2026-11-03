"""Engine inputs built straight from generated sample data, without a database.

Used by tests (rules, and agreement with the scalar engine) and by the benchmark's pure-matching stage.
Partner and rate-card ids follow the order of `reference_data`, as the seed script creates them.
"""

from datetime import datetime

import polars as pl

from app.sample_data.generator import SampleData
from app.services import reference_data as ref
from app.services.matching import Inputs

PARTNER_IDS = {name: index + 1 for index, (name, _, _) in enumerate(ref.PARTNERS)}


def reference_frames() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    partners = pl.DataFrame(
        {"id": [PARTNER_IDS[name] for name, _, _ in ref.PARTNERS], "kind": [kind for _, kind, _ in ref.PARTNERS],
         "settlement_days": [days for _, _, days in ref.PARTNERS]},
        schema={"id": pl.Int64, "kind": pl.String, "settlement_days": pl.Int64},
    )
    cards, slabs = [], []
    terms = ("commission_pct_bp", "fixed_fee_paise", "cod_fee_paise", "cod_fee_pct_bp", "gateway_pct_bp", "tcs_pct_bp", "tds_pct_bp")
    for card_id, (name, values) in enumerate(list(ref.CHANNEL_RATE_CARDS.items()) + list(ref.COURIER_RATE_CARDS.items()), start=1):
        cards.append({"id": card_id, "partner_id": PARTNER_IDS[name], "effective_from": ref.RATE_CARDS_EFFECTIVE_FROM,
                      **{term: int(values.get(term, 0)) for term in terms}})
        for leg in ("forward", "return"):
            for up_to_g, price in values.get(leg, []):
                slabs.append({"rate_card_id": card_id, "leg": leg, "up_to_g": up_to_g, "price_paise": price})
    rate_cards = pl.DataFrame(cards, schema={"id": pl.Int64, "partner_id": pl.Int64, "effective_from": pl.Date, **{term: pl.Int64 for term in terms}})
    slab_frame = pl.DataFrame(slabs, schema={"rate_card_id": pl.Int64, "leg": pl.String, "up_to_g": pl.Int64, "price_paise": pl.Int64})
    return partners, rate_cards, slab_frame


def inputs_from_sample(data: SampleData) -> Inputs:
    partners, rate_cards, slabs = reference_frames()
    orders = pl.DataFrame(
        [{
            "order_id": o["order_id"], "channel_partner_id": PARTNER_IDS[o["channel"]],
            "courier_partner_id": PARTNER_IDS[o["courier"]] if o["courier"] else None, "awb": o["awb"],
            "order_date": o["order_date"], "delivered_date": o["delivered_date"], "returned_date": o["returned_date"],
            "value_paise": o["value_paise"], "payment_mode": o["payment_mode"], "delivery_status": o["delivery_status"],
            "dead_weight_g": o["dead_weight_g"], "volumetric_weight_g": o["volumetric_weight_g"],
        } for o in data.orders],
        schema={"order_id": pl.String, "channel_partner_id": pl.Int64, "courier_partner_id": pl.Int64, "awb": pl.String,
                "order_date": pl.Date, "delivered_date": pl.Date, "returned_date": pl.Date, "value_paise": pl.Int64,
                "payment_mode": pl.String, "delivery_status": pl.String, "dead_weight_g": pl.Int64, "volumetric_weight_g": pl.Int64},
    )
    settlements = pl.DataFrame(
        [{"order_id": line["order_id"], "net_paise": line["net"], "tcs_paise": line["tcs"], "tds_paise": line["tds"]} for line in data.settlements],
        schema={"order_id": pl.String, "net_paise": pl.Int64, "tcs_paise": pl.Int64, "tds_paise": pl.Int64},
    )
    cod = pl.DataFrame(
        [{"order_id": line["order_id"], "awb": line["awb"], "amount_paise": line["amount"]} for line in data.cod_remittances],
        schema={"order_id": pl.String, "awb": pl.String, "amount_paise": pl.Int64},
    )
    # Courier B's freight invoice carries only the AWB, as in the real file.
    freight = pl.DataFrame(
        [{"order_id": line["order_id"] if line["courier"] == "Courier A" else None, "awb": line["awb"], "leg": line["leg"],
          "freight_paise": line["freight"], "cod_fee_paise": line["cod_fee"]} for line in data.freight_lines],
        schema={"order_id": pl.String, "awb": pl.String, "leg": pl.String, "freight_paise": pl.Int64, "cod_fee_paise": pl.Int64},
    )
    receipts = pl.DataFrame(
        [{"order_id": line["order_id"], "received_on": line["received_at"].date() if isinstance(line["received_at"], datetime) else line["received_at"]}
         for line in data.receipts],
        schema={"order_id": pl.String, "received_on": pl.Date},
    )
    return Inputs(orders=orders, partners=partners, rate_cards=rate_cards, slabs=slabs,
                  settlements=settlements, cod=cod, freight=freight, receipts=receipts)
