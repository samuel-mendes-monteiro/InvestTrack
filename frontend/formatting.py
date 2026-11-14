"""Brazilian number formatting and parsing for the UI."""

from decimal import Decimal, InvalidOperation


def brl(value) -> str:
    """'1234.5' -> 'R$ 1.234,50'. None -> '—'."""
    if value is None:
        return "—"
    us = f"{Decimal(value):,.2f}"  # 1,234.50
    return "R$ " + us.replace(",", "_").replace(".", ",").replace("_", ".")


def pct(value) -> str:
    """'8.57' -> '+8,57%'. None -> '—'."""
    if value is None:
        return "—"
    return f"{Decimal(value):+.2f}%".replace(".", ",")


def per_share(value) -> str:
    """'0.10245643978' -> 'R$ 0,10245644' (8 decimals at most). None -> '—'."""
    if value is None:
        return "—"
    d = Decimal(value).quantize(Decimal("0.00000001")).normalize()
    if d == d.to_integral():
        d = d.quantize(Decimal("0.01"))
    return "R$ " + f"{d:f}".replace(".", ",")


def quantity(value) -> str:
    """'150' -> '150', '0.5' -> '0,5' (no trailing zeros)."""
    d = Decimal(value).normalize()
    return f"{d:f}".replace(".", ",")


def parse_decimal(text: str) -> Decimal:
    """Parse what a user types: '30,50', '30.50', '1.234,56' or 'R$ 30,50'.

    A text field is used instead of st.number_input on purpose: number_input
    returns a float, and money never goes through float in this project.
    """
    s = text.strip().replace("R$", "").replace(" ", "")
    if "," in s:  # Brazilian format: dots are thousands, comma is decimal
        s = s.replace(".", "").replace(",", ".")
    try:
        value = Decimal(s)
    except InvalidOperation:
        raise ValueError(f"'{text}' não é um número válido") from None
    if not value.is_finite():
        raise ValueError(f"'{text}' não é um número válido")
    return value
