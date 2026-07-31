"""The dashboard's snapshot provider seam.

A ``Snapshot`` is a complete, self-contained view of dashboard state at one
point in time. Production adapters gather ``/proc``, ``sbx``, Git, log, and
GitHub information behind the ``SnapshotProvider`` boundary; tests inject
controlled snapshots directly so the Textual application can be exercised
without touching the host.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True, slots=True)
class HostRun:
    """One Sandcastle orchestration invocation discovered live."""

    id: str


@dataclass(frozen=True, slots=True)
class Snapshot:
    """A point-in-time view of all Host Runs known to the dashboard."""

    host_runs: Sequence[HostRun] = field(default_factory=tuple)


class SnapshotProvider(Protocol):
    """Supplies the dashboard with the latest known ``Snapshot``."""

    def get_snapshot(self) -> Snapshot:
        """Return the current snapshot.

        May perform blocking I/O; callers are responsible for running it off
        the UI thread.
        """
        ...
