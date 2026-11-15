"""Fixed income calculations, with numbers simple enough to check by hand."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from investtrack.core.fixed_income import (
    FixedIncome,
    Indexer,
    PartialRedemption,
    Product,
    RedemptionTooLargeError,
    daily_net_values,
    daily_series,
    gross_values,
    iof_rate,
    ir_rate,
    is_estimated,
    money_in,
    partial_valuations,
    taxes,
    value_on,
)
from investtrack.core.performance import portfolio_history

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


def test_applied_after_the_last_business_day_is_worth_the_amount():
    # Applied on a Sunday, after the last day with CDI: nothing earned, nothing owed yet.
    sunday = DAYS[-1] + timedelta(days=2)
    v = value_on(cdb(start=sunday), sunday, DAYS, ONE_PERCENT)
    assert (v.day, v.gross, v.net, v.gross_return) == (sunday, Decimal("1000"), Decimal("1000"), 0)
    # No history at all is different: still unknown, not 1000.
    assert value_on(cdb(start=sunday), sunday, [], {}) is None


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


def test_daily_net_values_take_the_taxes_out():
    taxed, exempt = cdb(), cdb(product=Product.LCI, redeemed_on=DAYS[2])
    gross, _ = daily_series([taxed, exempt], DAYS[:4], ONE_PERCENT)
    net = daily_net_values([taxed, exempt], DAYS[:4], ONE_PERCENT)

    assert set(net) == set(gross)  # the same days
    assert net[DAYS[0]] == gross[DAYS[0]] == Decimal("2000")  # no gain yet, no tax
    expected = taxes(taxed, DAYS[3], Decimal("1030.301")).net  # LCI already redeemed
    assert net[DAYS[3]] == expected < gross[DAYS[3]]


def test_money_in_counts_redemptions_until_today():
    redeemed = cdb(redeemed_on=DAYS[2])  # out at its gross value that day: 1020.10
    running = cdb(start=DAYS[1])
    half = cdb(partial=[PartialRedemption(DAYS[1], Decimal("400"))])
    assert money_in([redeemed, running, half], DAYS[:4], ONE_PERCENT, None, DAYS[3]) == Decimal(
        "1000"
    ) - Decimal("1020.1") + Decimal("1000") + Decimal("1000") - Decimal("400")
    # Before the redemption day, it is still in.
    assert money_in([redeemed], DAYS[:4], ONE_PERCENT, None, DAYS[1]) == Decimal("1000")


def test_twr_of_fixed_income_alone():
    values, flows = daily_series([cdb(rate="110")], DAYS[:3], ONE_PERCENT)
    history = portfolio_history([], DAYS[:3], {}, other_values=values, other_flows=flows)
    assert [h.twr for h in history] == [0, Decimal("0.011"), Decimal("1.011") ** 2 - 1]


# --- partial redemptions -----------------------------------------------------


def withdraw(day: date, gross: str) -> PartialRedemption:
    return PartialRedemption(day, Decimal(gross))


def test_partial_redemption_keeps_the_rest_growing():
    half = cdb(partial=(withdraw(DAYS[1], "505"),))  # half of the 1010 that day
    values = gross_values(half, DAYS[:3], ONE_PERCENT)
    assert values[DAYS[1]] == Decimal("505")
    assert values[DAYS[2]] == Decimal("510.05")  # half of 1020.1


def test_what_is_left_is_taxed_on_its_own_principal():
    half = cdb(partial=(withdraw(DAYS[1], "505"),))
    v = value_on(half, DAYS[2], DAYS[:3], ONE_PERCENT)
    # 500 of the 1000 are left: the gain is 10.05, IOF 93% on day 2.
    assert v.iof == Decimal("10.05") * Decimal("0.93")
    assert v.ir == (Decimal("10.05") - v.iof) * Decimal("0.225")


def test_each_withdrawal_is_taxed_on_its_share_of_the_gain():
    two = cdb(partial=(withdraw(DAYS[1], "252.5"), withdraw(DAYS[2], "255.025")))
    first, second = partial_valuations(two, DAYS[:3], ONE_PERCENT)
    # The first took a quarter (250 of principal, 2.50 of gain); the second
    # took a third of the rest, which is another quarter (5.025 of gain).
    assert first.iof == Decimal("2.5") * Decimal("0.96")
    assert second.iof == Decimal("5.025") * Decimal("0.93")
    left = value_on(two, DAYS[2], DAYS[:3], ONE_PERCENT)
    assert left.gross == Decimal("510.05")


def test_withdrawing_everything_is_refused():
    with pytest.raises(RedemptionTooLargeError) as exc:
        gross_values(cdb(partial=(withdraw(DAYS[1], "1010"),)), DAYS[:3], ONE_PERCENT)
    assert exc.value.available == Decimal("1010")


@pytest.mark.parametrize("day", [START, date(2028, 3, 2)])
def test_partial_redemption_must_be_inside_the_period(day):
    with pytest.raises(ValueError):
        cdb(partial=(withdraw(day, "10"),))


def test_partial_redemption_after_a_full_one_is_refused():
    with pytest.raises(ValueError):
        cdb(redeemed_on=DAYS[1], partial=(withdraw(DAYS[2], "10"),))


def test_partial_redemption_is_money_out_and_twr_ignores_it():
    half = cdb(partial=(withdraw(DAYS[1], "505"),))
    values, flows = daily_series([half], DAYS[:3], ONE_PERCENT)
    assert flows[DAYS[1]] == Decimal("-505")
    history = portfolio_history([], DAYS[:3], {}, other_values=values, other_flows=flows)
    assert history[-1].twr == Decimal("1.01") ** 2 - 1  # same as without withdrawing


# --- IPCA+ -------------------------------------------------------------------


def ipca_plus(rate="6", **kw):
    kw.setdefault("start", date(2026, 3, 1))
    return cdb(rate=rate, indexer=Indexer.IPCA, **kw)


MARCH_1PCT = {date(2026, 3, 1): Decimal("1")}


def test_ipca_plus_is_inflation_times_the_real_rate():
    days = [date(2026, 3, 1), date(2026, 4, 1)]  # one business day apart, for the math
    values = gross_values(ipca_plus(), days, {}, MARCH_1PCT)
    expected = Decimal("1000") * Decimal("1.06") ** (Decimal(1) / 252) * Decimal("1.01")
    assert values[days[1]] == expected


def test_ipca_is_spread_over_the_calendar_days_of_its_month():
    days = [date(2026, 4, 1), date(2026, 4, 16)]  # 15 of April's 30 days
    april = {date(2026, 4, 1): Decimal("1")}
    values = gross_values(ipca_plus(start=days[0]), days, {}, april)
    real = Decimal("1.06") ** (Decimal(1) / 252)
    assert values[days[1]] == Decimal("1000") * real * Decimal("1.01") ** Decimal("0.5")


def test_unpublished_month_repeats_the_last_one_and_is_an_estimate():
    investment = ipca_plus()
    days = [date(2026, 3, 1), date(2026, 4, 1), date(2026, 5, 1)]
    values = gross_values(investment, days, {}, MARCH_1PCT)
    inflation = values[days[2]] / (Decimal("1000") * Decimal("1.06") ** (Decimal(2) / 252))
    assert round(inflation, 20) == round(Decimal("1.01") ** 2, 20)  # April assumed 1% too
    assert not is_estimated(investment, days[1], MARCH_1PCT)  # March is published
    assert is_estimated(investment, days[2], MARCH_1PCT)  # April isn't
    assert not is_estimated(cdb(), days[2], MARCH_1PCT)


def test_ipca_plus_without_any_ipca_has_only_the_first_day():
    values = gross_values(ipca_plus(), [date(2026, 3, 1), date(2026, 3, 2)], {}, {})
    assert list(values) == [date(2026, 3, 1)]
