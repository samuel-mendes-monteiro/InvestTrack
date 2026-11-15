"""Demo: a database with a demo account, sample trades, income and fixed income.

Run with:  python -m investtrack.demo
Then log in to the web interface with the email and password printed.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from investtrack.auth import Auth
from investtrack.core.fixed_income import FixedIncome, Indexer, Product
from investtrack.core.income import Income, IncomeType, net_income_by_ticker
from investtrack.core.portfolio import AssetType, Operation, OpType
from investtrack.storage.db import create_db_engine, init_db
from investtrack.storage.models import OperationRecord, User
from investtrack.storage.repository import (
    add_fixed_income,
    add_income,
    add_operation,
    get_portfolio,
    income_to_domain,
    list_incomes,
    list_operations,
)


def _op(ticker, op_type, day, qty, price, fees="0"):
    return Operation(ticker, op_type, day, Decimal(qty), Decimal(price), Decimal(fees))


SAMPLE = [
    (_op("PETR4", OpType.BUY, date(2026, 1, 5), "100", "30", "10"), AssetType.STOCK),
    (_op("PETR4", OpType.BUY, date(2026, 2, 3), "100", "40", "10"), AssetType.STOCK),
    (_op("PETR4", OpType.SELL, date(2026, 3, 10), "50", "50", "10"), AssetType.STOCK),
    (_op("HGLG11", OpType.BUY, date(2026, 1, 20), "10", "158.40"), AssetType.FII),
    (_op("IVVB11", OpType.BUY, date(2026, 4, 2), "5", "352.15", "4.90"), AssetType.ETF),
    (_op("AAPL34", OpType.BUY, date(2026, 3, 2), "20", "62.40", "4.90"), AssetType.BDR),
]


def _inc(ticker, income_type, day, amount, tax="0"):
    return Income(ticker, income_type, day, Decimal(amount), Decimal(tax))


# Manual income only: PETR4, HGLG11 and IVVB11 income is computed by the API
# from B3's events, so entering it here would count it twice. B3 doesn't
# publish BDR dividends, which is what manual entries are for.
INCOME = [
    _inc("AAPL34", IncomeType.DIVIDEND, date(2026, 5, 18), "1.12", "0.34"),
    _inc("AAPL34", IncomeType.DIVIDEND, date(2026, 8, 17), "1.15", "0.35"),
]

FIXED_INCOME = [
    FixedIncome(
        "CDB Banco Demo",
        Product.CDB,
        Indexer.CDI,
        Decimal("110"),
        date(2026, 2, 2),
        date(2028, 2, 2),
        Decimal("5000"),
    ),
    FixedIncome(
        "LCI Banco Demo",
        Product.LCI,
        Indexer.PRE,
        Decimal("12.5"),
        date(2026, 4, 6),
        date(2027, 4, 6),
        Decimal("3000"),
    ),
]


DEMO_EMAIL = "demo@investtrack.local"
DEMO_PASSWORD = "demo-password"


def money(value: Decimal) -> str:
    """Round only for display, never during calculations."""
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"R$ {rounded:>10,.2f}"


def main() -> None:
    engine = create_db_engine()
    init_db(engine)

    with Session(engine) as session:
        user = session.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            if session.scalar(select(OperationRecord).where(OperationRecord.user_id.is_(None))):
                # The first account adopts data without an owner: a demo account
                # must never take someone's real portfolio.
                print("This database already has data from before accounts existed.")
                print("Create your own account in the web interface instead.")
                return
            user = Auth().register(session, DEMO_EMAIL, DEMO_PASSWORD)

        if not list_operations(session, user.id):
            for op, asset_type in SAMPLE:
                add_operation(session, user.id, op, asset_type)
            for income in INCOME:
                add_income(session, user.id, income)
            for investment in FIXED_INCOME:
                add_fixed_income(session, user.id, investment)
            print(
                f"Inserted {len(SAMPLE)} operations, {len(INCOME)} manual income and "
                f"{len(FIXED_INCOME)} fixed income into {engine.url}\n"
            )

        # Only manual entries here: B3 income is computed by the API.
        records = list_incomes(session, user.id)
        income = net_income_by_ticker([income_to_domain(r) for r in records])
        print(f"{'Ticker':<8} {'Qty':>8} {'Avg price':>13} {'Realized':>13} {'Income':>13}")
        for pos in get_portfolio(session, user.id).values():
            avg, realized = money(pos.avg_price), money(pos.realized_profit)
            received = money(income.get(pos.ticker, Decimal("0")))
            print(f"{pos.ticker:<8} {pos.quantity:>8} {avg} {realized} {received}")
        print(f"\nLog in with {DEMO_EMAIL} / {DEMO_PASSWORD}")

    engine.dispose()  # close pooled connections before the program exits


if __name__ == "__main__":
    main()
