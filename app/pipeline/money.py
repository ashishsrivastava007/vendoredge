"""
A genuinely currency-aware value type, built to replace scattered,
hardcoded "$"-and-bare-float handling across the codebase.

Root cause this exists to fix (found by direct audit, not assumption):
FinancialImpact and the evidence schema it's built from name every
amount field with a literal "_usd" suffix (annual_spend_usd,
potential_annual_impact_usd, etc.), and the frontend independently
hardcodes a literal "$" character at roughly a dozen separate render
sites. Neither of those was ever a display-only issue -- normalize.py's
own currency_calculation_safe flag was defined as
`not (currency_mismatch and "$" not in raw_question)`, where
`currency_mismatch = currency is not None`. That means ANY explicitly
stated currency -- including a clean, single, consistently-EUR case --
was being treated as unsafe to calculate at all, unless the raw text
happened to also contain a literal dollar sign somewhere. A case
entirely in EUR, with no dollar amount anywhere, was refused outright.

This module does not attempt to fix that gating logic itself (that fix
lives in normalize.py, where the actual signal -- which currency the
spend figure was reported in -- already exists via
common.supplier_currency and was simply never consulted). This module
is the one place amount+currency are represented and formatted, so nothing
downstream needs its own currency logic ever again.

Explicitly out of scope, per instruction: no FX conversion. A Money
value is only ever combined with another Money value when both share
the same currency; the arithmetic functions in scenario_engine.py
enforce that directly rather than silently converting.
"""
from pydantic import BaseModel


# Deliberately small and explicit rather than a large external library
# dependency -- these are the symbols VendorEdge's own evidence schema
# and classifier prompt already recognize (currency is extracted as a
# free-text code like "EUR", "GBP", "USD", "SEK"). Anything not in this
# map falls back to showing the ISO code itself, which is always
# unambiguous even without a symbol -- never guessed, never invented.
_SYMBOLS = {
    "USD": "$",
    "EUR": "\u20ac",
    "GBP": "\u00a3",
    "JPY": "\u00a5",
    "CHF": "CHF ",
    "SEK": "SEK ",
    "NOK": "NOK ",
    "DKK": "DKK ",
    "CAD": "CA$",
    "AUD": "A$",
    "CNY": "\u00a5",
    "INR": "\u20b9",
}


class Money(BaseModel):
    """An amount that is never separated from its currency. Every
    financial calculation in scenario_engine.py returns Money, not a
    bare float -- there is deliberately no way to construct a
    dimensionless amount from that module."""

    amount: float
    currency: str  # ISO 4217 code, e.g. "USD", "EUR", "GBP" -- never a symbol

    def formatted(self, decimals: int = 0) -> str:
        """'\u20ac610,500' for EUR, '$610,500' for USD, 'SEK 610,500' for a
        currency with no compact symbol, 'AED 610,500' for anything
        entirely unrecognized (falls back to the plain ISO code, which
        is always correct even without a symbol on file)."""
        symbol = _SYMBOLS.get(self.currency.upper())
        formatted_number = f"{self.amount:,.{decimals}f}"
        if symbol:
            return f"{symbol}{formatted_number}"
        return f"{self.currency.upper()} {formatted_number}"

    def __add__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(
                f"Cannot combine {self.currency} and {other.currency} without an "
                "explicit FX rate -- this is a deliberate hard stop, not a bug: "
                "silently mixing currencies is exactly the class of error this "
                "type exists to prevent."
            )
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: "Money") -> "Money":
        if self.currency != other.currency:
            raise ValueError(
                f"Cannot combine {self.currency} and {other.currency} without an "
                "explicit FX rate -- this is a deliberate hard stop, not a bug."
            )
        return Money(amount=self.amount - other.amount, currency=self.currency)


def currency_symbol(currency: str | None) -> str:
    """Used only by the handful of call sites that need a bare symbol
    rather than a formatted Money (e.g. a frontend label prefix). Falls
    back to the ISO code with a trailing space rather than guessing or
    defaulting to '$' -- an unrecognized or missing currency must never
    silently render as though it were USD."""
    if not currency:
        return ""
    symbol = _SYMBOLS.get(currency.upper())
    return symbol if symbol else f"{currency.upper()} "
