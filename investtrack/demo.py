"""Stage 2 demo: create the database, insert sample operations, print the portfolio.

Run with:  python -m investtrack.demo
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy.orm import Session

from investtrack.db import create_db_engine, init_db
from investtrack.models import AssetType
from investtrack.portfolio import Operation, OpType
from investtrack.repository import add_operation, get_portfolio, list_operations


def _op(ticker, op_type, day, qty, price, fees="0"):
    return Operation(ticker, op_type, day, Decimal(qty), Decimal(price), Decimal(fees))


SAMPLE = [
    (_op("PETR4", OpType.BUY, date(2026, 1, 5), "100", "30", "10"), AssetType.STOCK),
    (_op("PETR4", OpType.BUY, date(2026, 2, 3), "100", "40", "10"), AssetType.STOCK),
    (_op("PETR4", OpType.SELL, date(2026, 3, 10), "50", "50", "10"), AssetType.STOCK),
    (_op("HGLG11", OpType.BUY, date(2026, 1, 20), "10", "158.40"), AssetType.FII),
    (_op("IVVB11", OpType.BUY, date(2026, 4, 2), "5", "352.15", "4.90"), AssetType.ETF),
]


def money(value: Decimal) -> str:
    """Round only for display, never during calculations."""
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"R$ {rounded:>10,.2f}"


def main() -> None:
    engine = create_db_engine()
    init_db(engine)

    with Session(engine) as session:
        if not list_operations(session):
            for op, asset_type in SAMPLE:
                add_operation(session, op, asset_type)
            print(f"Inserted {len(SAMPLE)} sample operations into {engine.url}\n")

        print(f"{'Ticker':<8} {'Qty':>8} {'Avg price':>13} {'Realized':>13}")
        for pos in get_portfolio(session).values():
            avg, realized = money(pos.avg_price), money(pos.realized_profit)
            print(f"{pos.ticker:<8} {pos.quantity:>8} {avg} {realized}")

    engine.dispose()  # close pooled connections before the program exits


if __name__ == "__main__":
    main()
