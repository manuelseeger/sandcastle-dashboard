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
class Repository:
    """The Git repository associated with a Host Run's working directory."""

    path: str
    name: str


@dataclass(frozen=True, slots=True)
class HostRun:
    """One Sandcastle orchestration invocation discovered live.

    Retained for the dashboard session after its process disappears, with
    ``ended`` set to ``True`` to mark its outcome unknown: a separately
    launched dashboard cannot reliably observe the orchestration exit code.
    """

    id: str
    pid: int
    repository: Repository | None = None
    started_at: float | None = None
    process_state: str = "unknown"
    ended: bool = False
    process_group_pids: tuple[int, ...] = field(default_factory=tuple)
    cpu_percent: float | None = None
    memory_bytes: int | None = None
    invocation_id: str | None = None
    deployment_id: str | None = None


@dataclass(frozen=True, slots=True)
class Castle:
    """A running Docker Sandbox Castle correlated to a Host Run."""

    name: str
    host_run_id: str
    scope: str
    vm_state: str
    issue_number: int | None = None
    root_number: int | None = None
    branch: str | None = None
    uptime_seconds: float | None = None
    session_count: int | None = None


@dataclass(frozen=True, slots=True)
class Snapshot:
    """A point-in-time view of all Host Runs known to the dashboard."""

    host_runs: Sequence[HostRun] = field(default_factory=tuple)
    castles: Sequence[Castle] = field(default_factory=tuple)
    castle_discovery_error: str | None = None


class SnapshotProvider(Protocol):
    """Supplies the dashboard with the latest known ``Snapshot``."""

    def get_snapshot(self) -> Snapshot:
        """Return the current snapshot.

        May perform blocking I/O; callers are responsible for running it off
        the UI thread.
        """
        ...
