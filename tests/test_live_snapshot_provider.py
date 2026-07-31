"""Unit tests for the composed live Host Run snapshot provider."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from sandcastle_dashboard.live_snapshot_provider import LiveHostRunSnapshotProvider
from sandcastle_dashboard.snapshot import Repository


def _write_stat(
    pid_dir: Path,
    pid: int,
    ppid: int,
    state: str = "S",
    utime_ticks: int = 0,
    stime_ticks: int = 0,
    rss_pages: int = 0,
) -> None:
    fields = ["0"] * 22
    fields[0] = state
    fields[1] = str(ppid)
    fields[11] = str(utime_ticks)
    fields[12] = str(stime_ticks)
    fields[19] = "100"
    fields[21] = str(rss_pages)
    (pid_dir / "stat").write_text(f"{pid} (node) " + " ".join(fields))


def _write_orchestrator(
    proc_root: Path,
    pid: int,
    cwd: Path,
    utime_ticks: int = 0,
    stime_ticks: int = 0,
    rss_pages: int = 0,
) -> None:
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir()
    _write_stat(
        pid_dir,
        pid,
        ppid=1,
        utime_ticks=utime_ticks,
        stime_ticks=stime_ticks,
        rss_pages=rss_pages,
    )
    (pid_dir / "cmdline").write_bytes(b"node\x00.sandcastle/main.mts\x00")
    (pid_dir / "cwd").symlink_to(cwd)


def _write_uptime(proc_root: Path) -> None:
    (proc_root / "uptime").write_text("1000.0 900.0\n")


def _fake_git_runner(repo_path: Path):
    def runner(cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=f"{repo_path}\n", stderr=""
        )

    return runner


def test_get_snapshot_associates_host_run_with_repository_from_cwd(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _write_uptime(proc_root)
    _write_orchestrator(proc_root, pid=42, cwd=repo_dir)
    provider = LiveHostRunSnapshotProvider(
        proc_root=proc_root, git_runner=_fake_git_runner(repo_dir)
    )

    snapshot = provider.get_snapshot()

    assert len(snapshot.host_runs) == 1
    host_run = snapshot.host_runs[0]
    assert host_run.pid == 42
    assert host_run.repository == Repository(path=str(repo_dir), name=repo_dir.name)
    assert host_run.ended is False


def test_get_snapshot_retains_a_host_run_that_disappears_with_unknown_outcome(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _write_uptime(proc_root)
    _write_orchestrator(proc_root, pid=42, cwd=repo_dir)
    provider = LiveHostRunSnapshotProvider(
        proc_root=proc_root, git_runner=_fake_git_runner(repo_dir)
    )
    first = provider.get_snapshot()
    assert first.host_runs[0].ended is False

    shutil.rmtree(proc_root / "42")
    second = provider.get_snapshot()

    assert len(second.host_runs) == 1
    assert second.host_runs[0].pid == 42
    assert second.host_runs[0].ended is True


def test_get_snapshot_returns_empty_snapshot_when_no_orchestrator_is_discovered(
    tmp_path,
):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    _write_uptime(proc_root)
    provider = LiveHostRunSnapshotProvider(
        proc_root=proc_root, git_runner=_fake_git_runner(tmp_path)
    )

    snapshot = provider.get_snapshot()

    assert snapshot.host_runs == ()


def test_get_snapshot_reports_aggregated_memory_on_the_first_poll(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _write_uptime(proc_root)
    _write_orchestrator(proc_root, pid=42, cwd=repo_dir, rss_pages=100)
    provider = LiveHostRunSnapshotProvider(
        proc_root=proc_root, git_runner=_fake_git_runner(repo_dir)
    )

    snapshot = provider.get_snapshot()

    host_run = snapshot.host_runs[0]
    assert host_run.memory_bytes == 100 * 4096


def test_get_snapshot_reports_no_cpu_percent_on_the_first_poll(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _write_uptime(proc_root)
    _write_orchestrator(proc_root, pid=42, cwd=repo_dir, utime_ticks=10)
    provider = LiveHostRunSnapshotProvider(
        proc_root=proc_root, git_runner=_fake_git_runner(repo_dir)
    )

    snapshot = provider.get_snapshot()

    assert snapshot.host_runs[0].cpu_percent is None


def test_get_snapshot_computes_cpu_percent_from_the_second_poll_onward(
    tmp_path, monkeypatch
):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _write_uptime(proc_root)
    _write_orchestrator(proc_root, pid=42, cwd=repo_dir, utime_ticks=100)
    provider = LiveHostRunSnapshotProvider(
        proc_root=proc_root, git_runner=_fake_git_runner(repo_dir)
    )
    clock = iter([10.0, 12.0])
    monkeypatch.setattr(
        "sandcastle_dashboard.discovery.time.monotonic", lambda: next(clock)
    )
    monkeypatch.setattr("sandcastle_dashboard.discovery.time.time", lambda: 2_000.0)
    monkeypatch.setattr(
        "sandcastle_dashboard.discovery._clock_ticks_per_second", lambda: 100.0
    )
    provider.get_snapshot()

    _write_stat(proc_root / "42", pid=42, ppid=1, utime_ticks=300)
    snapshot = provider.get_snapshot()

    # (300 - 100) ticks / 100 ticks-per-second = 2 cpu-seconds over 2 wall seconds
    assert snapshot.host_runs[0].cpu_percent == 100.0
