"""Unit tests for the composed live Host Run snapshot provider."""

from __future__ import annotations

import json
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


def _fake_sbx_runner(listing_json: str, inspections_by_name: dict[str, str]):
    def run(args):
        args = tuple(args)
        if args == ("ls", "--json"):
            return subprocess.CompletedProcess(
                args=[], returncode=0, stdout=listing_json, stderr=""
            )
        name = args[1]
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=inspections_by_name[name], stderr=""
        )

    return run


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


def test_get_snapshot_correlates_a_running_castle_to_its_host_run(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _write_uptime(proc_root)
    _write_orchestrator(proc_root, pid=42, cwd=repo_dir)
    listing = json.dumps([{"name": "parames-prod-42-issue-9-abc", "status": "running"}])
    inspection = json.dumps(
        {"state": "running", "uptime_seconds": 10.0, "active_sessions": 1}
    )
    provider = LiveHostRunSnapshotProvider(
        proc_root=proc_root,
        git_runner=_fake_git_runner(repo_dir),
        sbx_runner=_fake_sbx_runner(
            listing, {"parames-prod-42-issue-9-abc": inspection}
        ),
    )

    snapshot = provider.get_snapshot()

    assert snapshot.castle_discovery_error is None
    assert len(snapshot.castles) == 1
    castle = snapshot.castles[0]
    assert castle.host_run_id == snapshot.host_runs[0].id
    assert castle.scope == "issue"
    assert castle.issue_number == 9


def _fake_branch_runner(branch_names: list[str]):
    def runner(cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout="\n".join(branch_names) + "\n", stderr=""
        )

    return runner


def test_get_snapshot_attaches_branch_when_it_exists_in_the_run_repository(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _write_uptime(proc_root)
    _write_orchestrator(proc_root, pid=42, cwd=repo_dir)
    listing = json.dumps([{"name": "parames-prod-42-issue-9-abc", "status": "running"}])
    inspection = json.dumps(
        {"state": "running", "uptime_seconds": 10.0, "active_sessions": 1}
    )
    provider = LiveHostRunSnapshotProvider(
        proc_root=proc_root,
        git_runner=_fake_git_runner(repo_dir),
        sbx_runner=_fake_sbx_runner(
            listing, {"parames-prod-42-issue-9-abc": inspection}
        ),
        branch_runner=_fake_branch_runner(["main", "sandcastle/issue-9"]),
    )

    snapshot = provider.get_snapshot()

    assert snapshot.castles[0].branch == "sandcastle/issue-9"


def test_get_snapshot_leaves_branch_unset_when_it_is_missing_from_the_run_repository(
    tmp_path,
):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _write_uptime(proc_root)
    _write_orchestrator(proc_root, pid=42, cwd=repo_dir)
    listing = json.dumps([{"name": "parames-prod-42-issue-9-abc", "status": "running"}])
    inspection = json.dumps(
        {"state": "running", "uptime_seconds": 10.0, "active_sessions": 1}
    )
    provider = LiveHostRunSnapshotProvider(
        proc_root=proc_root,
        git_runner=_fake_git_runner(repo_dir),
        sbx_runner=_fake_sbx_runner(
            listing, {"parames-prod-42-issue-9-abc": inspection}
        ),
        branch_runner=_fake_branch_runner(["main"]),
    )

    snapshot = provider.get_snapshot()

    assert snapshot.castles[0].branch is None


def test_get_snapshot_resolves_the_current_role_log_for_a_correlated_castle(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    logs_dir = repo_dir / ".sandcastle" / "logs"
    logs_dir.mkdir(parents=True)
    (logs_dir / "sandcastle-issue-9-implementer-42.log").write_text(
        "Run started 10:00\nexploring the repository\n"
    )
    _write_uptime(proc_root)
    _write_orchestrator(proc_root, pid=42, cwd=repo_dir)
    listing = json.dumps([{"name": "parames-prod-42-issue-9-abc", "status": "running"}])
    inspection = json.dumps(
        {"state": "running", "uptime_seconds": 10.0, "active_sessions": 1}
    )
    provider = LiveHostRunSnapshotProvider(
        proc_root=proc_root,
        git_runner=_fake_git_runner(repo_dir),
        sbx_runner=_fake_sbx_runner(
            listing, {"parames-prod-42-issue-9-abc": inspection}
        ),
        branch_runner=_fake_branch_runner(["main"]),
    )

    snapshot = provider.get_snapshot()

    castle = snapshot.castles[0]
    assert castle.phase == "implementer"
    assert castle.log_tail == ("Run started 10:00", "exploring the repository")
    assert castle.last_activity_at is not None
    assert snapshot.host_runs[0].last_activity_at == castle.last_activity_at


def test_get_snapshot_reports_provisioning_before_a_role_log_exists(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / ".sandcastle" / "logs").mkdir(parents=True)
    _write_uptime(proc_root)
    _write_orchestrator(proc_root, pid=42, cwd=repo_dir)
    listing = json.dumps([{"name": "parames-prod-42-issue-9-abc", "status": "running"}])
    inspection = json.dumps(
        {"state": "running", "uptime_seconds": 10.0, "active_sessions": 1}
    )
    provider = LiveHostRunSnapshotProvider(
        proc_root=proc_root,
        git_runner=_fake_git_runner(repo_dir),
        sbx_runner=_fake_sbx_runner(
            listing, {"parames-prod-42-issue-9-abc": inspection}
        ),
        branch_runner=_fake_branch_runner(["main"]),
    )

    snapshot = provider.get_snapshot()

    castle = snapshot.castles[0]
    assert castle.phase == "provisioning"
    assert castle.log_tail == ()
    assert castle.last_activity_at is None
    assert snapshot.host_runs[0].last_activity_at is None


def test_get_snapshot_reports_readable_castle_discovery_error_without_discarding_host_runs(
    tmp_path,
):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _write_uptime(proc_root)
    _write_orchestrator(proc_root, pid=42, cwd=repo_dir)

    def broken_sbx_runner(args):
        raise FileNotFoundError("sbx not found")

    provider = LiveHostRunSnapshotProvider(
        proc_root=proc_root,
        git_runner=_fake_git_runner(repo_dir),
        sbx_runner=broken_sbx_runner,
    )

    snapshot = provider.get_snapshot()

    assert snapshot.castles == ()
    assert snapshot.castle_discovery_error is not None
    assert len(snapshot.host_runs) == 1
