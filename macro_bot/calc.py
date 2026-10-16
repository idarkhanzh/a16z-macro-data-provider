"""Percent changes and number formatting, following BLS release conventions.

BLS computes published percent changes from the published index levels and rounds
half-up to one decimal. Values arrive from the API as decimal strings, so Decimal
keeps the arithmetic exact and the rounding identical to the official tables.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def pct_change(current: Decimal, base: Decimal, annualize: int | None = None) -> Decimal | None:
    """Percent change from base to current.

    With annualize=n the one-period ratio is compounded n times (n=4 turns a
    quarterly change into an annual rate, as in Productivity and Costs).
    """
    if base == 0:
        return None
    ratio = current / base
    if annualize:
        ratio **= annualize
    return (ratio - 1) * 100


def round_half_up(value: Decimal, decimals: int = 1) -> Decimal:
    """Round like the BLS tables (0.25 -> 0.3) and never return negative zero."""
    rounded = value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)
    return abs(rounded) if rounded == 0 else rounded


def format_number(
    value: Decimal | None,
    decimals: int = 1,
    signed: bool = False,
    suffix: str = "",
) -> str:
    """Format a value for a message: "+0.3%", "-0.4%", "0.0%", "4.2%", "+1,234K" or "n/a"."""
    if value is None:
        return "n/a"
    rounded = round_half_up(value, decimals)
    text = f"{rounded:,.{decimals}f}"
    if signed and rounded > 0:
        text = "+" + text
    return text + suffix
