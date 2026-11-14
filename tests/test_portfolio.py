from datetime import date
from decimal import Decimal

import pytest

from investtrack.portfolio import (
    InsufficientPositionError,
    Operation,
    OpType,
    StockEvent,
    StockEventType,
    applied_stock_events,
    calculate_portfolio,
    calculate_position,
    value_position,
)


def buy(day: int, qty: str, price: str, fees: str = "0", ticker: str = "PETR4"):
    return Operation(
        ticker, OpType.BUY, date(2026, 1, day), Decimal(qty), Decimal(price), Decimal(fees)
    )


def sell(day: int, qty: str, price: str, fees: str = "0", ticker: str = "PETR4"):
    return Operation(
        ticker, OpType.SELL, date(2026, 1, day), Decimal(qty), Decimal(price), Decimal(fees)
    )


# --- calculation rules -------------------------------------------------------


def test_example_from_project_doc():
    pos = calculate_position(
        [
            buy(1, "100", "30"),
            buy(2, "100", "40"),
            sell(3, "50", "50"),
        ]
    )
    assert pos.quantity == Decimal("150")
    assert pos.avg_price == Decimal("35")
    assert pos.realized_profit == Decimal("750")


def test_fees_raise_avg_price_and_reduce_profit():
    pos = calculate_position(
        [
            buy(1, "100", "30", fees="10"),  # cost 3010
            buy(2, "100", "40", fees="10"),  # cost 4010 -> 7020 / 200 = 35.10
            sell(3, "50", "50", fees="10"),  # 50 x (50 - 35.10) - 10 = 735
        ]
    )
    assert pos.quantity == Decimal("150")
    assert pos.avg_price == Decimal("35.10")
    assert pos.realized_profit == Decimal("735")


def test_selling_everything_resets_avg_price():
    pos = calculate_position([buy(1, "100", "30"), sell(2, "100", "35")])
    assert pos.quantity == 0
    assert pos.avg_price == 0
    assert pos.realized_profit == Decimal("500")


def test_buying_again_after_closing_starts_from_zero():
    pos = calculate_position(
        [
            buy(1, "100", "30"),
            sell(2, "100", "35"),
            buy(3, "10", "50"),
        ]
    )
    assert pos.quantity == Decimal("10")
    assert pos.avg_price == Decimal("50")  # not mixed with the old 30
    assert pos.realized_profit == Decimal("500")


def test_selling_more_than_position_raises():
    with pytest.raises(InsufficientPositionError) as exc:
        calculate_position([buy(1, "100", "30"), sell(2, "101", "35")])
    assert exc.value.available == Decimal("100")
    assert exc.value.requested == Decimal("101")


def test_operations_are_processed_in_date_order():
    ordered = [buy(1, "100", "30"), buy(2, "100", "40"), sell(3, "50", "50")]
    shuffled = [ordered[2], ordered[0], ordered[1]]
    assert calculate_position(shuffled) == calculate_position(ordered)


def test_sell_dated_before_any_buy_raises():
    # Entered after the buy, but dated before it: there was nothing to sell.
    with pytest.raises(InsufficientPositionError):
        calculate_position([buy(5, "100", "30"), sell(1, "10", "35")])


def test_loss_is_negative_realized_profit():
    pos = calculate_position([buy(1, "100", "30"), sell(2, "40", "25")])
    assert pos.realized_profit == Decimal("-200")


# --- portfolio ---------------------------------------------------------------


def test_portfolio_groups_by_ticker():
    portfolio = calculate_portfolio(
        [
            buy(1, "100", "30", ticker="PETR4"),
            buy(1, "10", "150", ticker="HGLG11"),
            buy(2, "100", "40", ticker="PETR4"),
        ]
    )
    assert set(portfolio) == {"PETR4", "HGLG11"}
    assert portfolio["PETR4"].avg_price == Decimal("35")
    assert portfolio["HGLG11"].quantity == Decimal("10")


def test_empty_portfolio():
    assert calculate_portfolio([]) == {}


def test_calculate_position_rejects_mixed_tickers():
    with pytest.raises(ValueError):
        calculate_position([buy(1, "1", "1", ticker="PETR4"), buy(1, "1", "1", ticker="VALE3")])


# --- operation validation ----------------------------------------------------


def test_ticker_is_normalized():
    assert buy(1, "1", "1", ticker=" petr4 ").ticker == "PETR4"


def test_op_type_accepts_string():
    op = Operation("PETR4", "SELL", date(2026, 1, 1), Decimal("1"), Decimal("1"))
    assert op.op_type is OpType.SELL


@pytest.mark.parametrize(
    "qty, price, fees",
    [
        ("0", "10", "0"),  # zero quantity
        ("-1", "10", "0"),  # negative quantity
        ("1", "-10", "0"),  # negative price
        ("1", "10", "-1"),  # negative fees
    ],
)
def test_invalid_values_are_rejected(qty, price, fees):
    with pytest.raises(ValueError):
        buy(1, qty, price, fees)


def test_float_is_rejected():
    with pytest.raises(TypeError):
        Operation("PETR4", OpType.BUY, date(2026, 1, 1), Decimal("1"), 30.0)


# --- valuation ---------------------------------------------------------------


def test_valuation_example_from_project_doc():
    pos = calculate_position(
        [
            buy(1, "100", "30"),
            buy(2, "100", "40"),
            sell(3, "50", "50"),
        ]
    )
    v = value_position(pos, Decimal("38"))
    assert v.invested == Decimal("5250")
    assert v.current_value == Decimal("5700")
    assert v.result == Decimal("450")
    assert v.result_pct.quantize(Decimal("0.01")) == Decimal("8.57")


def test_valuation_of_closed_position():
    pos = calculate_position([buy(1, "100", "30"), sell(2, "100", "35")])
    v = value_position(pos, Decimal("40"))
    assert v.result == 0
    assert v.result_pct is None


# --- stock events (splits, reverse splits, bonus shares) ----------------------


def event(day, kind, multiplier, unit_cost="0", ticker="PETR4"):
    return StockEvent(ticker, kind, date(2026, 1, day), Decimal(multiplier), Decimal(unit_cost))


SPLIT, REVERSE, BONUS = StockEventType.SPLIT, StockEventType.REVERSE_SPLIT, StockEventType.BONUS


def test_split_keeps_total_cost():
    pos = calculate_position([buy(1, "100", "30")], [event(5, SPLIT, "2")])
    assert pos.quantity == 200
    assert pos.avg_price == 15
    assert pos.quantity * pos.avg_price == Decimal("3000")


def test_selling_the_split_shares_is_allowed():
    pos = calculate_position([buy(1, "100", "30"), sell(6, "200", "20")], [event(5, SPLIT, "2")])
    assert pos.quantity == 0
    assert pos.realized_profit == Decimal("1000")  # 200 x (20 - 15)


def test_split_does_not_count_before_it_happens():
    with pytest.raises(InsufficientPositionError):
        calculate_position([buy(1, "100", "30"), sell(4, "200", "20")], [event(5, SPLIT, "2")])


def test_event_applies_after_trades_of_its_record_date():
    pos = calculate_position([buy(1, "100", "30"), buy(5, "100", "30")], [event(5, SPLIT, "2")])
    assert pos.quantity == 400  # the buy on the record date is split too


def test_reverse_split_drops_fraction_and_its_cost():
    pos = calculate_position([buy(1, "15", "10")], [event(5, REVERSE, "0.1")])
    assert pos.quantity == 1  # 1.5 shares: the half is sold by B3 in an auction
    assert pos.avg_price == 100  # unchanged by rounding: 150 / 1.5


def test_reverse_split_below_one_share_closes_position():
    pos = calculate_position([buy(1, "5", "10")], [event(5, REVERSE, "0.1")])
    assert (pos.quantity, pos.avg_price) == (0, 0)


def test_bonus_without_attributed_cost():
    pos = calculate_position([buy(1, "100", "30")], [event(5, BONUS, "1.1")])
    assert pos.quantity == 110
    assert pos.quantity * pos.avg_price == Decimal("3000")


def test_bonus_with_attributed_cost():
    pos = calculate_position([buy(1, "100", "30")], [event(5, BONUS, "1.1", unit_cost="4")])
    assert pos.quantity == 110
    assert pos.quantity * pos.avg_price == Decimal("3040")  # 3000 + 10 new shares x 4


def test_events_of_other_tickers_and_closed_positions_are_ignored():
    ops = [buy(1, "100", "30"), sell(2, "100", "30")]
    pos = calculate_position(ops, [event(5, SPLIT, "2"), event(5, SPLIT, "2", ticker="VALE3")])
    assert pos.quantity == 0


def test_realized_profit_is_not_touched_by_events():
    ops = [buy(1, "100", "30"), sell(2, "50", "40")]
    pos = calculate_position(ops, [event(5, SPLIT, "2")])
    assert pos.realized_profit == Decimal("500")
    assert pos.quantity == 100


def test_float_multiplier_is_rejected():
    with pytest.raises(TypeError):
        StockEvent("PETR4", SPLIT, date(2026, 1, 1), 2.0)


def test_applied_stock_events():
    ops = [buy(1, "100", "30"), buy(1, "10", "158", ticker="HGLG11")]
    events = [
        event(5, SPLIT, "2"),
        event(8, BONUS, "1.1"),
        event(9, SPLIT, "10", ticker="VALE3"),  # never held
        event(9, SPLIT, "10", ticker="HGLG11"),
    ]
    applied = applied_stock_events(ops, events)
    assert [(a.event.ticker, a.quantity_before, a.quantity_after) for a in applied] == [
        ("PETR4", 100, 200),
        ("PETR4", 200, 220),
        ("HGLG11", 10, 100),
    ]
