"""Turkish number formatting shared by every user-facing text (decimal comma)."""

from __future__ import annotations


def dec(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def km(m: float, nd: int = 1) -> str:
    return f"{dec(m / 1000, nd)} km"


def coord(lat: float, lon: float) -> str:
    """Same format as the field reports, so the operator can compare by eye."""
    return f"{lat:.4f}N {lon:.4f}E"
