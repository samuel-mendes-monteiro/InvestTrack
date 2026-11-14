"""Where market prices come from.

The API depends on the PriceProvider interface, not on a concrete source.
Stage 3 uses fixed prices; stage 4 adds a provider that calls brapi.dev
with a cache, and the API code does not need to change.
"""

from decimal import Decimal
from typing import Protocol


class PriceProvider(Protocol):
    def get_price(self, ticker: str) -> Decimal | None:
        """Current price, or None if it is unknown."""
        ...


class StaticPriceProvider:
    """Returns prices from a fixed table. Used until real quotes exist."""

    def __init__(self, prices: dict[str, Decimal]):
        self._prices = {t.upper(): p for t, p in prices.items()}

    def get_price(self, ticker: str) -> Decimal | None:
        return self._prices.get(ticker.upper())


# Placeholder quotes for stage 3, replaced by brapi in stage 4.
DEMO_PRICES = StaticPriceProvider({
    "PETR4": Decimal("38.00"),
    "HGLG11": Decimal("160.50"),
    "IVVB11": Decimal("360.20"),
    "VALE3": Decimal("62.30"),
    "ITUB4": Decimal("35.80"),
})
