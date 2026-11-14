"""Fixed income calculations, with numbers simple enough to check by hand."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from investtrack.fixed_income import (
    FixedIncome,
    Indexer,
    Product,
    daily_series,
    gross_values,
    iof_rate,
    ir_rate,
    taxes,
    value_on,
)
from investtrack.performance import portfolio_history

START = date(2026, 3, 2)
DAYS = [date(2026, 3, d) for d in (2, 3, 4, 5, 6)]


def cdb(rate="100", indexer=Indexer.CDI, product=Product.CDB, amount="1000", **kw):
    kw.setdefault("start", START)
    kw.setdefault("maturity", date(2028, 3, 2))
    return FixedIncome("CDB Banco X", product, indexer, Decimal(rate), amount=Decimal(amount), **kw)


ONE_PERCENT = {d: Decimal("1") for d in DAYS}  # 1% a day: easy to follow


def test_cdi_compounds_daily():
    values = gross_values(cdb(), DAYS[:3], ONE_PERCENT)
    assert list(values.values()) == [Decimal("1000"), Decimal("1010"), Decimal("1020.1")]


def test_percentage_of_cdi():
    values = gross_values(cdb(rate="110"), DAYS[:2], ONE_PERCENT)
    assert values[DAYS[1]] == Decimal("1011")  # 1% x 110%


def test_prefixed_uses_252_business_days():
    days = [START + timedelta(days=i) for i in range(253)]  # any 253 business days
    values = gross_values(cdb(rate="12", indexer=Indexer.PRE), days, {})
    assert values[days[0]] == 1000
    assert values[days[252]] == Decimal("1120")  # exactly one year: +12%


def test_values_stop_at_redemption():
    values = gross_values(cdb(redeemed_on=DAYS[2]), DAYS, ONE_PERCENT)
    assert max(values) == DAYS[2]


def test_values_stop_where_cdi_is_missing():
    rates = {DAYS[0]: Decimal("1")}
    values = gross_values(cdb(), DAYS, rates)
    assert max(values) == DAYS[1]  # day 2 needs day 1's rate, which isn't published


@pytest.mark.parametrize(
    "days, rate",
    [(1, "0.225"), (180, "0.225"), (181, "0.20"), (360, "0.20"), (720, "0.175"), (721, "0.15")],
)
def test_ir_table(days, rate):
    assert ir_rate(days) == Decimal(rate)


@pytest.mark.parametrize(
    "days, rate", [(0, "1"), (1, "0.96"), (10, "0.66"), (29, "0.03"), (30, "0")]
)
def test_iof_table(days, rate):
    assert iof_rate(days) == Decimal(rate)


def test_cdb_taxes_after_a_year():
    v = taxes(cdb(), START + timedelta(days=400), Decimal("1100"))
    assert (v.iof, v.ir, v.net) == (0, Decimal("17.5"), Decimal("1082.5"))


def test_cdb_taxes_within_30_days():
    v = taxes(cdb(), START + timedelta(days=10), Decimal("1100"))
    assert v.iof == Decimal("66")  # 66% of the 100 gain
    assert v.ir == Decimal("7.65")  # 22.5% of the remaining 34
    assert v.net == Decimal("1026.35")


@pytest.mark.parametrize("product", [Product.LCI, Product.LCA])
def test_lci_and_lca_are_tax_exempt(product):
    v = taxes(cdb(product=product), START + timedelta(days=10), Decimal("1100"))
    assert v.net == Decimal("1100")


def test_no_tax_without_gain():
    assert taxes(cdb(), START, Decimal("1000")).net == Decimal("1000")


def test_value_on_uses_last_day_with_data():
    v = value_on(cdb(), date(2026, 3, 8), DAYS[:3], ONE_PERCENT)  # a Sunday
    assert (v.day, v.gross) == (DAYS[2], Decimal("1020.1"))
    assert value_on(cdb(), date(2026, 3, 1), DAYS, ONE_PERCENT) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"amount": "0"},
        {"rate": "0"},
        {"maturity": START},
        {"redeemed_on": START - timedelta(days=1)},
        {"redeemed_on": date(2029, 1, 1)},
    ],
)
def test_invalid_investments(changes):
    with pytest.raises(ValueError):
        cdb(**changes)


def test_blank_name_and_float_are_rejected():
    with pytest.raises(ValueError):
        FixedIncome(" ", Product.CDB, Indexer.CDI, Decimal("100"), START, DAYS[4], Decimal("1"))
    with pytest.raises(TypeError):
        FixedIncome("X", Product.CDB, Indexer.CDI, 100.0, START, DAYS[4], Decimal("1"))


def test_daily_series_flows_in_and_out():
    redeemed = cdb(redeemed_on=DAYS[2])
    running = cdb(start=DAYS[1])
    values, flows = daily_series([redeemed, running], DAYS[:4], ONE_PERCENT)

    assert flows[DAYS[0]] == Decimal("1000")  # first one applied
    assert flows[DAYS[1]] == Decimal("1000")  # second one applied
    assert flows[DAYS[2]] == Decimal("-1020.1")  # first one redeemed at its gross value
    assert values[DAYS[1]] == Decimal("1010") + Decimal("1000")
    assert values[DAYS[2]] == Decimal("1010")  # only the one still invested
    assert values[DAYS[3]] == Decimal("1020.1")


def test_twr_of_fixed_income_alone():
    values, flows = daily_series([cdb(rate="110")], DAYS[:3], ONE_PERCENT)
    history = portfolio_history([], DAYS[:3], {}, other_values=values, other_flows=flows)
    assert [h.twr for h in history] == [0, Decimal("0.011"), Decimal("1.011") ** 2 - 1]
