"""Reads host-wide capacity used to scale the dashboard's resource bars."""

from __future__ import annotations

import os


def cpu_count() -> int:
    """The number of logical CPUs, used to scale an aggregated CPU percentage."""
    return os.cpu_count() or 1


def total_memory_bytes() -> int:
    """Total physical memory in bytes, used to scale the resident memory bar.

    Returns ``0`` when the host doesn't expose this (e.g. an unsupported
    platform), which callers treat as an unknown scale.
    """
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except AttributeError, ValueError, OSError:
        return 0
    if pages < 0 or page_size < 0:
        return 0
    return pages * page_size
