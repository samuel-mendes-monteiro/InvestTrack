"""Reading B3's trade statement ("Extrato de Negociação", from the Área do Investidor).

Only this module knows the file's format. It turns the spreadsheet into
plain rows; deciding which are new and whether they are valid is done by
the import functions with the calculation core, like any other operation.

Why the trade statement and not the movement one ("Movimentação"): the
movement statement is dated by settlement, two business days after the
trade (D+2). A buy made on a record date would show up after it, and its
income and the order of the trades (which sets the average price) would
be wrong.

Quirks of the file:
- dates come as text ("20/10/2026"), numbers as Excel numbers (floats);
- fractional-lot trades have an "F" after the ticker (RECV3F is RECV3);
- B3's files may declare a wrong sheet size (<dimension ref="A1"/>), and
  openpyxl's fast mode trusts it and reads only the first cell, so the
  size is recomputed before reading.
"""

import io
import re
import warnings
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from investtrack.models import AssetType
from investtrack.portfolio import OpType

MAX_FILE_SIZE = 5 * 1024 * 1024  # a statement of several years is a few hundred KB

COLUMNS = {
    "date": "Data do Negócio",
    "type": "Tipo de Movimentação",
    "market": "Mercado",
    "ticker": "Código de Negociação",
    "quantity": "Quantidade",
    "price": "Preço",
}
OP_TYPES = {"compra": OpType.BUY, "venda": OpType.SELL}
SPOT_MARKETS = {"mercado à vista", "mercado fracionário"}

FRACTIONAL = re.compile(r"^([A-Z0-9]{4}\d{1,2})F$")
BDR = re.compile(r"^[A-Z0-9]{4}3[2-59]$")  # 32, 33, 34, 35, 39


class StatementError(ValueError):
    """The file is not a B3 trade statement this module can read."""


@dataclass(frozen=True)
class StatementRow:
    line: int  # row number in the spreadsheet, for messages
    date: date
    op_type: OpType
    ticker: str
    quantity: Decimal
    price: Decimal


@dataclass(frozen=True)
class SkippedRow:
    line: int
    reason: str  # e.g. "OPTIONS_MARKET"
    detail: str  # what the row said, for the user


def normalize_ticker(ticker: str) -> str:
    """'RECV3F' -> 'RECV3': the fractional lot is the same share."""
    ticker = ticker.strip().upper()
    match = FRACTIONAL.match(ticker)
    return match.group(1) if match else ticker


def guess_asset_type(ticker: str) -> AssetType:
    """Only a hint for tickers seen for the first time.

    The suffix tells shares (3-8) and BDRs (32-39) apart, but "11" may be an
    FII, an ETF or a unit. Little depends on it: B3 events tell funds from
    companies by ISIN, whatever the type says.
    """
    if BDR.match(ticker):
        return AssetType.BDR
    if ticker.endswith("11"):
        return AssetType.FII
    return AssetType.STOCK


def _decimal(value) -> Decimal:
    """Excel numbers arrive as floats; repr gives back the decimal that was
    typed (12.66, not 12.6600000000000001...), so money never does float math."""
    if isinstance(value, bool):
        raise ValueError("not a number")
    if isinstance(value, int | float):
        return Decimal(repr(value))
    return Decimal(str(value).strip().replace(".", "").replace(",", "."))


def _date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value).strip(), "%d/%m/%Y").date()


def read_statement(data: bytes) -> tuple[list[StatementRow], list[SkippedRow]]:
    """Trades of the spot market, and the rows left out with the reason."""
    if len(data) > MAX_FILE_SIZE:
        raise StatementError("file too large")
    try:
        with warnings.catch_warnings():
            # B3's files have no default style; harmless, but openpyxl warns.
            warnings.simplefilter("ignore", UserWarning)
            workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError) as e:
        raise StatementError("not an Excel (.xlsx) file") from e

    try:
        sheet = workbook.worksheets[0]
        sheet.reset_dimensions()  # don't trust the size the file declares
        rows = sheet.iter_rows(values_only=True)
        header = [str(h).strip() if h is not None else "" for h in next(rows, ())]
        try:
            index = {key: header.index(name) for key, name in COLUMNS.items()}
        except ValueError:
            raise StatementError(
                "missing columns: is this the trade statement (Negociação)?"
            ) from None

        trades, skipped = [], []
        for line, row in enumerate(rows, start=2):
            if not row or all(v is None or str(v).strip() == "" for v in row):
                continue

            def cell(key, row=row):
                i = index[key]
                return row[i] if i < len(row) else None

            kind = str(cell("type") or "").strip().lower()
            market = str(cell("market") or "").strip().lower()
            detail = f"{cell('type')} {cell('quantity')} {cell('ticker')} ({cell('market')})"
            if market not in SPOT_MARKETS:
                skipped.append(SkippedRow(line, "UNSUPPORTED_MARKET", detail))
                continue
            if kind not in OP_TYPES:
                skipped.append(SkippedRow(line, "UNKNOWN_TYPE", detail))
                continue
            try:
                trade = StatementRow(
                    line=line,
                    date=_date(cell("date")),
                    op_type=OP_TYPES[kind],
                    ticker=normalize_ticker(str(cell("ticker"))),
                    quantity=_decimal(cell("quantity")),
                    price=_decimal(cell("price")),
                )
            except (ValueError, InvalidOperation, TypeError):
                skipped.append(SkippedRow(line, "UNREADABLE_ROW", detail))
                continue
            if trade.quantity <= 0 or trade.price < 0:
                skipped.append(SkippedRow(line, "UNREADABLE_ROW", detail))
                continue
            trades.append(trade)
        return trades, skipped
    finally:
        workbook.close()
