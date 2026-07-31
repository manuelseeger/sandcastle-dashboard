"""Human-readable formatting for the dashboard's status view."""

from __future__ import annotations

import time

_BYTE_UNITS = ("B", "KiB", "MiB", "GiB", "TiB")


def format_duration(seconds: float) -> str:
    """Format a non-negative duration compactly, e.g. ``1h02m03s``."""
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m{secs:02d}s"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def format_bytes(num_bytes: int) -> str:
    """Format a byte count using binary units, e.g. ``512.0MiB``."""
    value = float(num_bytes)
    for unit in _BYTE_UNITS[:-1]:
        if value < 1024:
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}{_BYTE_UNITS[-1]}"


def format_timestamp(epoch_seconds: float) -> str:
    """Format an epoch timestamp for display in the local timezone."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch_seconds))
