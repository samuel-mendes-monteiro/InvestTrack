"""TWR and benchmark calculations, with scenarios simple enough to check by hand."""

from datetime import date
from decimal import Decimal

from investtrack.income import Income, IncomeSource, IncomeType
from investtrack.performance import (
    Period,
    cdi_accumulated,
    index_return,
    months_before,
    portfolio_history,
    rebase,
    window_base,
)
from investtrack.portfolio import Operation, OpType, StockEvent, StockEventType

D = [date(2026, 3, d) for d in (2, 3, 4, 5, 6)]  # Monday to Friday


def buy(day, qty, price, fees="0", ticker="PETR4"):
    return Operation(ticker, OpType.BUY, day, Decimal(qty), Decimal(price), Decimal(fees))


def sell(day, qty, price, fees="0", ticker="PETR4"):
    return Operation(ticker, OpType.SELL, day, Decimal(qty), Decimal(price), Decimal(fees))


def closes(*prices, ticker="PETR4"):
    return {ticker: {D[i]: Decimal(p) for i, p in enumerate(prices) if p is not None}}


def twr(history):
    return [round(h.twr * 100, 4) for h in history]


def test_returns_are_chained():
    history = portfolio_history([buy(D[0], "100", "10")], D[:3], closes("10", "11", "12.1"))
    assert twr(history) == [0, 10, 21]
    assert history[-1].value == Decimal("1210")


def test_new_money_does_not_change_the_return():
    ops = [buy(D[0], "100", "10"), buy(D[2], "1000", "11")]  # 10x more money on day 3
    history = portfolio_history(ops, D[:4], closes("10", "11", "11", "12.1"))
    assert twr(history) == [0, 10, 10, 21]  # same as without the second buy
    assert history[2].flow == Decimal("11000")


def test_fees_lower_the_return():
    history = portfolio_history([buy(D[0], "100", "10", fees="10")], D[:1], closes("10"))
    assert history[0].twr == Decimal("1000") / Decimal("1010") - 1


def test_income_counts_as_return():
    dividend = Income("PETR4", IncomeType.DIVIDEND, D[1], Decimal("50"), source=IncomeSource.B3)
    history = portfolio_history(
        [buy(D[0], "100", "10")], D[:2], closes("10", "10"), incomes=[dividend]
    )
    assert twr(history) == [0, 5]


def test_jcp_counts_net_of_tax():
    jcp = Income("PETR4", IncomeType.JCP, D[1], Decimal("100"), tax=Decimal("15"))
    history = portfolio_history([buy(D[0], "100", "10")], D[:2], closes("10", "10"), incomes=[jcp])
    assert twr(history)[-1] == Decimal("8.5")


def test_selling_everything_keeps_the_return_until_then():
    ops = [buy(D[0], "100", "10"), sell(D[2], "100", "12")]
    history = portfolio_history(ops, D[:4], closes("10", "11", "12", "15"))
    assert twr(history) == [0, 10, 20, 20]  # the jump to 15 after selling doesn't count
    assert history[-1].value == 0


def test_split_does_not_look_like_a_crash():
    split = StockEvent("PETR4", StockEventType.SPLIT, D[1], Decimal("2"))
    history = portfolio_history(
        [buy(D[0], "100", "10")], D[:3], closes("10", "10", "5"), stock_events=[split]
    )
    assert twr(history) == [0, 0, 0]  # 100 x 10 = 200 x 5


def test_missing_close_uses_the_last_known_one():
    history = portfolio_history([buy(D[0], "100", "10")], D[:3], closes("10", None, "11"))
    assert twr(history) == [0, 0, 10]


def test_asset_without_any_close_uses_trade_price():
    history = portfolio_history([buy(D[0], "100", "10", ticker="XPTO3")], D[:2], {})
    assert twr(history) == [0, 0]
    assert history[0].value == Decimal("1000")


def test_weekend_trade_counts_on_monday():
    saturday = date(2026, 2, 28)
    history = portfolio_history([buy(saturday, "100", "10")], D[:2], closes("10", "11"))
    assert [h.date for h in history] == D[:2]
    assert twr(history) == [0, 10]


def test_two_assets():
    ops = [buy(D[0], "100", "10"), buy(D[0], "10", "100", ticker="HGLG11")]
    prices = closes("10", "11") | closes("100", "100", ticker="HGLG11")
    history = portfolio_history(ops, D[:2], prices)
    assert twr(history) == [0, 5]  # half the money up 10%, half flat


def test_empty():
    assert portfolio_history([], D, {}) == []


# --- benchmarks --------------------------------------------------------------


def test_cdi_is_earned_overnight():
    rates = {D[0]: Decimal("1"), D[1]: Decimal("1"), D[2]: Decimal("1")}
    acc = cdi_accumulated(rates, D[:3], start=D[0])
    assert [acc[d] for d in D[:3]] == [0, Decimal("0.01"), Decimal("0.0201")]


def test_ibovespa_from_the_previous_close():
    values = {date(2026, 2, 27): Decimal("100"), D[0]: Decimal("110"), D[2]: Decimal("121")}
    ret = index_return(values, D[:3], start=D[0])
    assert [ret[d] for d in D[:3]] == [Decimal("0.1"), Decimal("0.1"), Decimal("0.21")]


def test_index_without_data():
    assert index_return({}, D, start=D[0]) == {}


# --- periods -----------------------------------------------------------------


def test_months_before_clamps_to_the_end_of_the_month():
    assert months_before(date(2026, 11, 13), 1) == date(2026, 10, 13)
    assert months_before(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert months_before(date(2026, 1, 15), 12) == date(2025, 1, 15)
    assert months_before(date(2026, 5, 31), 6) == date(2025, 11, 30)


DAYS = [date(2026, 1, 5), date(2026, 2, 2), date(2026, 2, 4), date(2026, 3, 3)]


def test_window_starts_at_the_last_close_before_the_period():
    # 03/03 - 1 month = 03/02, not a trading day here: the close before is 02/02.
    assert window_base(DAYS, Period.MONTH) == date(2026, 2, 2)


def test_a_week_starts_at_the_close_seven_days_before():
    week = [date(2026, 11, d) for d in (5, 6, 9, 10, 11, 12, 13)]  # Thu, Fri, Mon..Fri
    assert window_base(week, Period.WEEK) == date(2026, 11, 6)  # 13/11 - 7 days
    # A holiday on that day: the close before it.
    assert window_base([d for d in week if d.day != 6], Period.WEEK) == date(2026, 11, 5)


def test_window_longer_than_the_history_shows_everything():
    assert window_base(DAYS, Period.YEAR) is None
    assert window_base(DAYS, Period.ALL) is None
    assert window_base([], Period.MONTH) is None


def test_rebase_is_exact_for_chained_returns():
    # +10% then +20% is +32% in all; the second part alone is +20%.
    assert rebase(Decimal("0.32"), Decimal("0.1")) == Decimal("0.2")
    assert rebase(Decimal("0.1"), Decimal("0.1")) == 0
