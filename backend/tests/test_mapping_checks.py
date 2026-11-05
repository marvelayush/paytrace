"""Plausibility checks: columns that parse fine but are the wrong ones."""

import polars as pl

from app.services.mapping_checks import plausibility_warnings

COLUMNS = {name: name.title() for name in ("gross", "commission", "fees", "tcs", "tds", "net")}


def _settlement(tcs: int, tds: int, net_offset: int = 0) -> pl.DataFrame:
    # 1,000.00 gross, 200 commission, 50 fees; amounts in paise
    gross, commission, fees = 100_000, 20_000, 5_000
    net = gross - commission - fees - tcs - tds + net_offset
    return pl.DataFrame({name: [value] * 20 for name, value in
                         {"gross": gross, "commission": commission, "fees": fees, "tcs": tcs, "tds": tds, "net": net}.items()})


def test_correct_settlement_has_no_warnings():
    assert plausibility_warnings("settlement", _settlement(tcs=500, tds=100), COLUMNS) == {}


def test_swapped_tcs_and_tds_are_flagged_on_both_fields():
    warnings = plausibility_warnings("settlement", _settlement(tcs=100, tds=500), COLUMNS)
    assert set(warnings) == {"tcs", "tds"}
    assert "swapped" in warnings["tcs"]
    assert "0.10% of gross" in warnings["tcs"]


def test_amounts_that_do_not_add_up_flag_net():
    warnings = plausibility_warnings("settlement", _settlement(tcs=500, tds=100, net_offset=30_000), COLUMNS)
    assert set(warnings) == {"net"}
    assert "20 of 20" in warnings["net"]


def test_rounding_within_a_rupee_is_accepted():
    assert plausibility_warnings("settlement", _settlement(tcs=500, tds=100, net_offset=99), COLUMNS) == {}


def test_unmapped_fields_and_other_file_kinds_are_not_checked():
    assert plausibility_warnings("settlement", _settlement(tcs=100, tds=500), {"gross": "Gross", "net": "Net"}) != {}
    assert plausibility_warnings("cod_remittance", _settlement(tcs=100, tds=500), COLUMNS) == {}
