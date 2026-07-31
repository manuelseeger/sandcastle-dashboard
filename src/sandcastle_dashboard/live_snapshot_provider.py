"""Production ``SnapshotProvider`` assembled from live host discovery."""

from __future__ import annotations

from pathlib import Path

from sandcastle_dashboard.discovery import (
    HostRunProcessGroup,
    discover_host_run_processes,
)
from sandcastle_dashboard.host_run_tracker import HostRunTracker
from sandcastle_dashboard.repository import (
    GitRunner,
    resolve_repository,
    run_git_toplevel,
)
from sandcastle_dashboard.resource_usage import ResourceUsageSampler
from sandcastle_dashboard.snapshot import HostRun, Snapshot


class LiveHostRunSnapshotProvider:
    """Discovers Host Runs from ``/proc`` and retains ones that disappear."""

    def __init__(
        self,
        proc_root: Path = Path("/proc"),
        git_runner: GitRunner = run_git_toplevel,
    ) -> None:
        self._proc_root = proc_root
        self._git_runner = git_runner
        self._tracker = HostRunTracker()
        self._resource_sampler = ResourceUsageSampler()

    def get_snapshot(self) -> Snapshot:
        groups = discover_host_run_processes(self._proc_root)
        discovered = tuple(self._to_host_run(group) for group in groups)
        return Snapshot(host_runs=self._tracker.update(discovered))

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
        )
