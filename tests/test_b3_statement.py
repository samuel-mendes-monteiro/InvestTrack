"""B3 trade statement: reading the file and planning the import.

The spreadsheets are built here with openpyxl, in the layout of a real
statement, with made-up trades.
"""

import io
import re
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from openpyxl import Workbook

from investtrack.b3_statement import (
    MAX_FILE_SIZE,
    StatementError,
    StatementRow,
    guess_asset_type,
    normalize_ticker,
    read_statement,
)
from investtrack.models import AssetType
from investtrack.portfolio import Operation, OpType, StockEvent, StockEventType
from investtrack.statement_import import Status, plan_import

HEADER = [
    "Data do Negócio",
    "Tipo de Movimentação",
    "Mercado",
    "Prazo/Vencimento",
    "Instituição",
    "Código de Negociação",
    "Quantidade",
    "Preço",
    "Valor",
]


def trade(
    day="20/10/2026", kind="Compra", market="Mercado à Vista", ticker="PETR4", qty=100, price=30.5
):
    value = qty * price if isinstance(qty, int | float) and isinstance(price, int | float) else "-"
    return [day, kind, market, "-", "CORRETORA X", ticker, qty, price, value]


def statement(*rows, header=HEADER, wrong_dimension=False) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Negociação"
    ws.append(header)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    data = buffer.getvalue()
    if wrong_dimension:  # like B3's files: the sheet claims to be a single cell
        data = _rewrite_sheet(
            data, lambda xml: re.sub(r'<dimension ref="[^"]+"', '<dimension ref="A1"', xml)
        )
    return data


def _rewrite_sheet(data: bytes, change) -> bytes:
    source, target = zipfile.ZipFile(io.BytesIO(data)), io.BytesIO()
    with zipfile.ZipFile(target, "w") as out:
        for item in source.infolist():
            content = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                content = change(content.decode()).encode()
            out.writestr(item, content)
    return target.getvalue()


# --- reading -----------------------------------------------------------------


def test_reads_trades():
    rows, skipped = read_statement(statement(trade(), trade(kind="Venda", qty=10, price=35)))
    assert skipped == []
    assert rows == [
        StatementRow(2, date(2026, 10, 20), OpType.BUY, "PETR4", Decimal("100"), Decimal("30.5")),
        StatementRow(3, date(2026, 10, 20), OpType.SELL, "PETR4", Decimal("10"), Decimal("35")),
    ]


def test_prices_are_the_decimals_that_were_typed():
    [row], _ = read_statement(statement(trade(price=12.66, qty=9)))
    assert row.price == Decimal("12.66")  # not 12.660000000000000142...


def test_fractional_lot_is_the_same_share():
    [row], _ = read_statement(statement(trade(market="Mercado Fracionário", ticker="RECV3F")))
    assert row.ticker == "RECV3"


def test_wrong_declared_size_is_ignored():
    rows, _ = read_statement(statement(trade(), trade(), wrong_dimension=True))
    assert len(rows) == 2  # openpyxl alone would read only cell A1


def test_text_numbers_and_excel_dates_are_read():
    [row], _ = read_statement(statement(trade(day=date(2026, 10, 20), qty="1.000", price="12,66")))
    assert (row.date, row.quantity, row.price) == (date(2026, 10, 20), 1000, Decimal("12.66"))


def test_rows_left_out_say_why():
    rows, skipped = read_statement(
        statement(
            trade(market="Opção de Compra", ticker="PETRK300"),
            trade(kind="Exercício"),
            trade(day="31/02/2026"),
            trade(qty=0),
            [None] * 9,  # blank row: ignored silently
            trade(),
        )
    )
    assert len(rows) == 1
    assert [(s.line, s.reason) for s in skipped] == [
        (2, "UNSUPPORTED_MARKET"),
        (3, "UNKNOWN_TYPE"),
        (4, "UNREADABLE_ROW"),
        (5, "UNREADABLE_ROW"),
    ]


def test_other_statements_are_refused():
    movements = ["Entrada/Saída", "Data", "Movimentação", "Produto", "Instituição", "Quantidade"]
    with pytest.raises(StatementError, match="Negociação"):
        read_statement(statement(header=movements))


@pytest.mark.parametrize("data", [b"not a spreadsheet", b"PK\x03\x04broken zip"])
def test_non_excel_files_are_refused(data):
    with pytest.raises(StatementError, match="xlsx"):
        read_statement(data)


def test_large_files_are_refused():
    with pytest.raises(StatementError, match="too large"):
        read_statement(b"x" * (MAX_FILE_SIZE + 1))


@pytest.mark.parametrize(
    "ticker, expected",
    [("RECV3F", "RECV3"), ("taee11f", "TAEE11"), ("PETR4", "PETR4"), ("BOVA11", "BOVA11")],
)
def test_normalize_ticker(ticker, expected):
    assert normalize_ticker(ticker) == expected


@pytest.mark.parametrize(
    "ticker, kind",
    [
        ("PETR4", AssetType.STOCK),
        ("AAPL34", AssetType.BDR),
        ("HGLG11", AssetType.FII),
        ("TAEE3", AssetType.STOCK),
    ],
)
def test_guess_asset_type(ticker, kind):
    assert guess_asset_type(ticker) is kind


# --- planning ----------------------------------------------------------------


def row(line, kind=OpType.BUY, qty="100", price="30", day=5, ticker="PETR4"):
    return StatementRow(line, date(2026, 1, day), kind, ticker, Decimal(qty), Decimal(price))


def op(kind=OpType.BUY, qty="100", price="30", day=5, ticker="PETR4", fees="0"):
    return Operation(ticker, kind, date(2026, 1, day), Decimal(qty), Decimal(price), Decimal(fees))


def statuses(plan):
    return [p.status for p in plan]


def test_new_rows():
    assert statuses(plan_import([], [row(2), row(3, OpType.SELL, qty="50")])) == [Status.NEW] * 2


def test_existing_operations_are_duplicates_even_with_fees():
    plan = plan_import([op(fees="4.90")], [row(2, price="30.00")])
    assert statuses(plan) == [Status.DUPLICATE]


def test_identical_trades_are_counted_one_by_one():
    # One identical buy already registered, two in the file: one of them is new.
    assert statuses(plan_import([op()], [row(2), row(3)])) == [Status.DUPLICATE, Status.NEW]


def test_importing_the_same_file_twice_adds_nothing():
    rows = [row(2), row(3, OpType.SELL, qty="50", day=6)]
    already = [op(), op(OpType.SELL, qty="50", day=6)]
    assert statuses(plan_import(already, rows)) == [Status.DUPLICATE] * 2


def test_sale_without_shares_rejects_the_tickers_new_rows():
    plan = plan_import(
        [],
        [row(2, qty="10"), row(3, OpType.SELL, qty="50", day=6), row(4, ticker="VALE3")],
    )
    assert statuses(plan) == [Status.REJECTED, Status.REJECTED, Status.NEW]
    assert plan[1].error.available == 10


def test_sale_covered_by_existing_operations():
    plan = plan_import([op(qty="100")], [row(2, OpType.SELL, qty="80", day=6)])
    assert statuses(plan) == [Status.NEW]


def test_splits_count_when_validating():
    split = StockEvent("PETR4", StockEventType.SPLIT, date(2026, 1, 5), Decimal("2"))
    plan = plan_import([op(qty="100")], [row(2, OpType.SELL, qty="200", day=6)], [split])
    assert statuses(plan) == [Status.NEW]
