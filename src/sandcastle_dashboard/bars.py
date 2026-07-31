"""Renders dense, btop-style resource bars for the dashboard's status view."""

from __future__ import annotations

_FULL_BLOCK = "█"
_EMPTY_BLOCK = "░"


def render_bar(fraction: float | None, width: int = 20) -> str:
    """Render a ``width``-character block bar for ``fraction``.

    ``fraction`` is clamped to ``[0, 1]`` for the bar's fill even when the
    underlying value exceeds it (e.g. a multi-core CPU aggregate). ``None``
    renders an empty bar to represent a reading that isn't available yet.
    """
    if fraction is None:
        return _EMPTY_BLOCK * width
    clamped = max(0.0, min(1.0, fraction))
    filled = round(clamped * width)
    return _FULL_BLOCK * filled + _EMPTY_BLOCK * (width - filled)
