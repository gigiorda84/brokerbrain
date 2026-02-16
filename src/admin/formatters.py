"""Jinja2 custom filters for Italian locale formatting.

All filters are registered on the Jinja2 environment in web.py.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal


def format_currency(value: Decimal | float | int | None) -> str:
    """Format as Italian currency: 1234.50 -> "1.234,50"."""
    if value is None:
        return "-"
    d = Decimal(str(value))
    # Format with 2 decimal places, then swap separators for Italian locale
    formatted = f"{d:,.2f}"
    # US: 1,234.50 -> Italian: 1.234,50
    formatted = formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    return formatted


def format_date(value: datetime | None) -> str:
    """Format as DD/MM/YYYY."""
    if value is None:
        return "-"
    return value.strftime("%d/%m/%Y")


def format_datetime(value: datetime | None) -> str:
    """Format as DD/MM/YYYY HH:MM."""
    if value is None:
        return "-"
    return value.strftime("%d/%m/%Y %H:%M")


def format_percentage(value: float | Decimal | None) -> str:
    """Format as Italian percentage: 0.243 -> "24,3%"."""
    if value is None:
        return "-"
    pct = float(value) * 100
    formatted = f"{pct:.1f}".replace(".", ",")
    return f"{formatted}%"


def format_duration_mins(start: datetime | None, end: datetime | None = None) -> str:
    """Format duration between two datetimes as 'Xm Ys'.

    If end is None, uses current UTC time.
    """
    if start is None:
        return "-"
    if end is None:
        from datetime import UTC

        end = datetime.now(UTC)
    delta = end - start
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "0s"
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def format_confidence(value: float | None) -> str:
    """Format confidence as percentage: 0.95 -> "95%"."""
    if value is None:
        return "-"
    return f"{value:.0%}"
