"""Retains Host Runs across dashboard polls, including ones that disappear."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from sandcastle_dashboard.snapshot import HostRun


class HostRunTracker:
    """Merges freshly discovered Host Runs with previously known ones.

    A Host Run that stops being discovered is retained in memory for the
    life of the tracker and relabeled ``ended`` with an unknown outcome: a
    separately launched dashboard cannot reliably observe an orchestration
    invocation's exit code.
    """

    def __init__(self) -> None:
        self._known: dict[str, HostRun] = {}

    def update(self, discovered: Sequence[HostRun]) -> tuple[HostRun, ...]:
        """Record ``discovered`` runs and return every known run, newest first."""
        discovered_ids = set()
        for run in discovered:
            discovered_ids.add(run.id)
            self._known[run.id] = run
        for run_id, run in self._known.items():
            if run_id not in discovered_ids and not run.ended:
                self._known[run_id] = dataclasses.replace(run, ended=True)
        return tuple(
            sorted(self._known.values(), key=_started_at_sort_key, reverse=True)
        )


def _started_at_sort_key(run: HostRun) -> float:
    return run.started_at if run.started_at is not None else float("-inf")
