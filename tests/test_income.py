from datetime import date
from decimal import Decimal

import pytest

from investtrack.income import (
    JCP_TAX_RATE,
    Income,
    IncomeEvent,
    IncomeSource,
    IncomeType,
    IncomeWithoutPositionError,
    check_incomes,
    incomes_from_events,
    monthly_income,
    net_income_by_ticker,
    quantity_on,
)
from investtrack.portfolio import Operation, OpType, StockEvent, StockEventType


def income(month, day, amount, tax="0", kind=IncomeType.DIVIDEND, ticker="ITSA4"):
    return Income(ticker, kind, date(2026, month, day), Decimal(amount), Decimal(tax))


def buy(month, day, ticker="ITSA4"):
    return Operation(ticker, OpType.BUY, date(2026, month, day), Decimal("100"), Decimal("10"))


def sell(month, day, ticker="ITSA4"):
    return Operation(ticker, OpType.SELL, date(2026, month, day), Decimal("100"), Decimal("11"))


# --- validation --------------------------------------------------------------


def test_net_is_amount_minus_withheld_tax():
    jcp = income(3, 1, "100", tax="15", kind=IncomeType.JCP)
    assert jcp.net == Decimal("85")


def test_ticker_and_type_are_normalized():
    i = Income(" itsa4 ", "JCP", date(2026, 1, 1), Decimal("1"))
    assert i.ticker == "ITSA4"
    assert i.income_type is IncomeType.JCP


@pytest.mark.parametrize(
    "amount, tax",
    [("0", "0"), ("-1", "0"), ("10", "-1"), ("10", "10.01")],
)
def test_invalid_amounts(amount, tax):
    with pytest.raises(ValueError):
        income(1, 1, amount, tax)


def test_float_is_rejected():
    with pytest.raises(TypeError):
        Income("ITSA4", IncomeType.DIVIDEND, date(2026, 1, 1), 0.1)


def test_unknown_type_is_rejected():
    with pytest.raises(ValueError):
        Income("ITSA4", "BONUS", date(2026, 1, 1), Decimal("1"))


# --- check_incomes -----------------------------------------------------------


def test_income_on_or_after_first_buy_is_valid():
    check_incomes([buy(1, 10)], [income(1, 10, "5"), income(2, 1, "5")])


def test_income_after_selling_everything_is_valid():
    # Held on the record date, sold, then the payment arrived.
    check_incomes([buy(1, 10), sell(2, 1)], [income(2, 15, "5")])


def test_income_before_first_buy_is_refused():
    with pytest.raises(IncomeWithoutPositionError) as exc:
        check_incomes([buy(3, 1), buy(1, 10)], [income(1, 5, "5")])
    assert exc.value.first_buy == date(2026, 1, 10)  # earliest buy, not the first listed


def test_income_for_ticker_never_bought_is_refused():
    with pytest.raises(IncomeWithoutPositionError) as exc:
        check_incomes([buy(1, 1, ticker="PETR4")], [income(2, 1, "5")])
    assert exc.value.first_buy is None


# --- aggregations ------------------------------------------------------------


def test_net_income_by_ticker():
    totals = net_income_by_ticker(
        [
            income(1, 5, "10"),
            income(2, 5, "100", tax="15", kind=IncomeType.JCP),
            income(1, 5, "8.40", kind=IncomeType.DISTRIBUTION, ticker="HGLG11"),
        ]
    )
    assert totals == {"ITSA4": Decimal("95"), "HGLG11": Decimal("8.40")}


def test_monthly_income_groups_by_month_and_type():
    months = monthly_income(
        [
            income(3, 20, "100", tax="15", kind=IncomeType.JCP),
            income(1, 15, "8.40", kind=IncomeType.DISTRIBUTION, ticker="HGLG11"),
            income(3, 1, "10"),
            income(1, 14, "0.10"),
            income(1, 16, "0.20"),
        ]
    )
    assert [(m.year, m.month) for m in months] == [(2026, 1), (2026, 3)]  # Feb omitted

    jan, mar = months
    assert jan.dividend == Decimal("0.3")  # exact: no float rounding
    assert jan.distribution == Decimal("8.40")
    assert jan.net == Decimal("8.70")
    assert mar.jcp == Decimal("85")
    assert mar.tax == Decimal("15")
    assert mar.net == Decimal("95")


def test_monthly_income_empty():
    assert monthly_income([]) == []


# --- income computed from events ---------------------------------------------


def event(month, day, rate, kind=IncomeType.DIVIDEND, pay=(None, None), ticker="ITSA4"):
    payment = date(2026, *pay) if pay[0] else date(2026, month, day + 10)
    return IncomeEvent(ticker, kind, date(2026, month, day), payment, Decimal(rate))


def test_quantity_on_counts_trades_of_that_day():
    ops = [buy(1, 10), buy(2, 1), sell(2, 2)]
    assert quantity_on(ops, date(2026, 1, 9)) == 0
    assert quantity_on(ops, date(2026, 1, 10)) == 100
    assert quantity_on(ops, date(2026, 2, 1)) == 200
    assert quantity_on(ops, date(2026, 2, 2)) == 100


def test_income_from_event():
    [i] = incomes_from_events([buy(1, 10)], [event(2, 5, "0.12345678901")])
    assert i.source is IncomeSource.B3
    assert i.quantity == 100
    assert i.amount == Decimal("12.345678901")  # full precision, rounded only for display
    assert i.tax == 0
    assert i.date == date(2026, 2, 15)


def test_jcp_has_tax_withheld():
    [i] = incomes_from_events([buy(1, 10)], [event(2, 5, "1", kind=IncomeType.JCP)])
    assert i.tax == Decimal("15") == i.amount * JCP_TAX_RATE
    assert i.net == Decimal("85")


def test_custom_jcp_rate():
    [i] = incomes_from_events(
        [buy(1, 10)], [event(2, 5, "1", kind=IncomeType.JCP)], jcp_tax_rate=Decimal("0.2")
    )
    assert i.tax == Decimal("20")


def test_events_without_entitlement_produce_nothing():
    events = [
        event(1, 5, "1"),  # before the buy
        event(3, 5, "1"),  # after selling everything
        event(2, 5, "1", ticker="PETR4"),  # another ticker
        event(2, 5, "0"),  # zero rate
    ]
    assert incomes_from_events([buy(1, 10), sell(2, 20)], events) == []


def test_event_without_payment_date_is_left_out():
    e = IncomeEvent("ITSA4", IncomeType.DIVIDEND, date(2026, 2, 5), None, Decimal("1"))
    assert incomes_from_events([buy(1, 10)], [e]) == []


def test_event_rejects_float_rate():
    with pytest.raises(TypeError):
        IncomeEvent("ITSA4", IncomeType.DIVIDEND, date(2026, 2, 5), None, 0.1)


def test_income_after_a_split_uses_the_new_quantity():
    split = StockEvent("ITSA4", StockEventType.SPLIT, date(2026, 1, 20), Decimal("2"))
    [i] = incomes_from_events([buy(1, 10)], [event(2, 5, "1")], stock_events=[split])
    assert i.quantity == 200


def test_income_on_the_split_record_date_uses_the_old_quantity():
    split = StockEvent("ITSA4", StockEventType.SPLIT, date(2026, 2, 5), Decimal("2"))
    [i] = incomes_from_events([buy(1, 10)], [event(2, 5, "1")], stock_events=[split])
    assert i.quantity == 100  # announced per share as they were before the split
