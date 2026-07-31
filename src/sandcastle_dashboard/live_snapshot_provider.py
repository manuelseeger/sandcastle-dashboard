"""Production ``SnapshotProvider`` assembled from live host discovery."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path

from sandcastle_dashboard.branch_identity import (
    BranchRunner,
    attach_branches,
    list_local_branches,
    run_git_local_branches,
)
from sandcastle_dashboard.castle_correlation import correlate_castles
from sandcastle_dashboard.discovery import (
    HostRunProcessGroup,
    discover_host_run_processes,
)
from sandcastle_dashboard.host_run_tracker import HostRunTracker
from sandcastle_dashboard.logs import resolve_castle_log
from sandcastle_dashboard.repository import (
    GitRunner,
    resolve_repository,
    run_git_toplevel,
)
from sandcastle_dashboard.resource_usage import ResourceUsageSampler
from sandcastle_dashboard.sbx import SbxRunner, discover_running_castles, run_sbx
from sandcastle_dashboard.snapshot import Castle, HostRun, Snapshot

_LOGS_SUBDIRECTORY = Path(".sandcastle") / "logs"


class LiveHostRunSnapshotProvider:
    """Discovers Host Runs from ``/proc`` and their running Castles via `sbx`.

    Host Runs that disappear are retained by the tracker; running Castles
    are freshly discovered and correlated on every poll.
    """

    def __init__(
        self,
        proc_root: Path = Path("/proc"),
        git_runner: GitRunner = run_git_toplevel,
        sbx_runner: SbxRunner = run_sbx,
        branch_runner: BranchRunner = run_git_local_branches,
    ) -> None:
        self._proc_root = proc_root
        self._git_runner = git_runner
        self._sbx_runner = sbx_runner
        self._branch_runner = branch_runner
        self._tracker = HostRunTracker()
        self._resource_sampler = ResourceUsageSampler()

    def get_snapshot(self) -> Snapshot:
        groups = discover_host_run_processes(self._proc_root)
        discovered = tuple(self._to_host_run(group) for group in groups)
        host_runs = self._tracker.update(discovered)
        castle_discovery = discover_running_castles(self._sbx_runner)
        castles = correlate_castles(castle_discovery.castles, host_runs)
        castles = attach_branches(
            castles,
            host_runs,
            list_branches=lambda path: list_local_branches(
                path, run=self._branch_runner
            ),
        )
        host_runs_by_id = {run.id: run for run in host_runs}
        castles = tuple(
            self._resolve_log(castle, host_runs_by_id.get(castle.host_run_id))
            for castle in castles
        )
        host_runs = tuple(self._attach_last_activity(run, castles) for run in host_runs)
        return Snapshot(
            host_runs=host_runs,
            castles=castles,
            castle_discovery_error=castle_discovery.error,
        )

    def _resolve_log(self, castle: Castle, host_run: HostRun | None) -> Castle:
        if host_run is None or host_run.repository is None:
            return castle
        logs_dir = Path(host_run.repository.path) / _LOGS_SUBDIRECTORY
        selection = resolve_castle_log(logs_dir, castle)
        return dataclasses.replace(
            castle,
            phase=selection.phase,
            last_activity_at=selection.last_activity_at,
            log_tail=selection.log_tail,
        )

    def _attach_last_activity(
        self, host_run: HostRun, castles: Sequence[Castle]
    ) -> HostRun:
        activity_times = [
            castle.last_activity_at
            for castle in castles
            if castle.host_run_id == host_run.id and castle.last_activity_at is not None
        ]
        if not activity_times:
            return host_run
        return dataclasses.replace(host_run, last_activity_at=max(activity_times))

    def _to_host_run(self, group: HostRunProcessGroup) -> HostRun:
        repository = resolve_repository(group.cwd, run=self._git_runner)
        run_id = f"{group.pid}:{group.started_at}"
        cpu_percent = self._resource_sampler.sample(
            run_id, cpu_seconds=group.cpu_seconds, sampled_at=group.sampled_at
        )
        return HostRun(
            id=run_id,
            pid=group.pid,
            repository=repository,
            started_at=group.started_at,
            process_state=group.process_state,
            process_group_pids=tuple(sorted(group.member_pids)),
            cpu_percent=cpu_percent,
            memory_bytes=group.memory_bytes,
            invocation_id=group.invocation_id,
            deployment_id=group.deployment_id,
        )
