"""Unit tests for /proc-based Host Run process discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from sandcastle_dashboard.discovery import discover_host_run_processes


def _write_stat(
    pid_dir: Path,
    pid: int,
    comm: str,
    ppid: int,
    state: str,
    starttime_ticks: int,
    utime_ticks: int = 0,
    stime_ticks: int = 0,
    rss_pages: int = 0,
) -> None:
    fields = ["0"] * 22
    fields[0] = state
    fields[1] = str(ppid)
    fields[11] = str(utime_ticks)
    fields[12] = str(stime_ticks)
    fields[19] = str(starttime_ticks)
    fields[21] = str(rss_pages)
    (pid_dir / "stat").write_text(f"{pid} ({comm}) " + " ".join(fields))


def _write_cmdline(pid_dir: Path, argv: list[str]) -> None:
    payload = b"\x00".join(part.encode() for part in argv)
    if argv:
        payload += b"\x00"
    (pid_dir / "cmdline").write_bytes(payload)


def _write_process(
    proc_root: Path,
    pid: int,
    ppid: int,
    argv: list[str],
    *,
    comm: str = "node",
    state: str = "S",
    starttime_ticks: int = 100,
    cwd: Path | None = None,
    utime_ticks: int = 0,
    stime_ticks: int = 0,
    rss_pages: int = 0,
    environ: dict[str, str] | None = None,
) -> Path:
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir()
    _write_stat(
        pid_dir,
        pid,
        comm,
        ppid,
        state,
        starttime_ticks,
        utime_ticks=utime_ticks,
        stime_ticks=stime_ticks,
        rss_pages=rss_pages,
    )
    _write_cmdline(pid_dir, argv)
    if cwd is not None:
        (pid_dir / "cwd").symlink_to(cwd)
    if environ is not None:
        payload = b"\x00".join(f"{k}={v}".encode() for k, v in environ.items())
        (pid_dir / "environ").write_bytes(payload + b"\x00")
    return pid_dir


def _write_uptime(proc_root: Path, uptime_seconds: float = 1000.0) -> None:
    (proc_root / "uptime").write_text(f"{uptime_seconds} 900.0\n")


def test_discover_host_run_processes_with_no_orchestrator_finds_no_groups(tmp_path):
    _write_uptime(tmp_path)
    _write_process(tmp_path, pid=50, ppid=1, argv=["bash"])

    groups = discover_host_run_processes(tmp_path)

    assert groups == []


def test_discover_host_run_processes_groups_npm_tsx_wrappers_under_orchestrator_pid(
    tmp_path,
):
    _write_uptime(tmp_path)
    repo_dir = tmp_path.parent / "repo"
    repo_dir.mkdir()
    _write_process(
        tmp_path,
        pid=10,
        ppid=1,
        argv=["npm", "--prefix", ".sandcastle", "run", "sandcastle"],
        comm="npm",
    )
    _write_process(
        tmp_path, pid=11, ppid=10, argv=["tsx", ".sandcastle/main.mts"], comm="node"
    )
    _write_process(
        tmp_path,
        pid=12,
        ppid=11,
        argv=["node", ".sandcastle/main.mts"],
        comm="node",
        cwd=repo_dir,
    )

    groups = discover_host_run_processes(tmp_path)

    assert len(groups) == 1
    group = groups[0]
    assert group.pid == 12
    assert group.member_pids == frozenset({10, 11, 12})
    assert group.cwd == repo_dir


def test_discover_host_run_processes_groups_node_launched_tsx_under_child_orchestrator(
    tmp_path,
):
    _write_uptime(tmp_path)
    _write_process(
        tmp_path,
        pid=10,
        ppid=1,
        argv=["npm", "--prefix", ".sandcastle", "run", "sandcastle"],
        comm="npm",
    )
    _write_process(
        tmp_path,
        pid=11,
        ppid=10,
        argv=[
            "node",
            "/project/.sandcastle/node_modules/.bin/tsx",
            ".sandcastle/main.mts",
        ],
    )
    _write_process(
        tmp_path,
        pid=12,
        ppid=11,
        argv=["node", ".sandcastle/main.mts"],
    )

    groups = discover_host_run_processes(tmp_path)

    assert len(groups) == 1
    assert groups[0].pid == 12
    assert groups[0].member_pids == frozenset({10, 11, 12})


def test_discover_host_run_processes_groups_descendant_processes_under_orchestrator_pid(
    tmp_path,
):
    _write_uptime(tmp_path)
    _write_process(tmp_path, pid=20, ppid=1, argv=["node", ".sandcastle/main.mts"])
    _write_process(tmp_path, pid=21, ppid=20, argv=["sbx", "exec", "claude"])
    _write_process(tmp_path, pid=22, ppid=21, argv=["claude"])

    groups = discover_host_run_processes(tmp_path)

    assert len(groups) == 1
    assert groups[0].member_pids == frozenset({20, 21, 22})


def test_discover_host_run_processes_excludes_unrelated_processes(tmp_path):
    _write_uptime(tmp_path)
    _write_process(tmp_path, pid=30, ppid=1, argv=["node", ".sandcastle/main.mts"])
    _write_process(tmp_path, pid=99, ppid=1, argv=["bash"])

    groups = discover_host_run_processes(tmp_path)

    assert len(groups) == 1
    assert 99 not in groups[0].member_pids


def test_discover_host_run_processes_derives_started_at_from_starttime_and_uptime(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("sandcastle_dashboard.discovery.time.time", lambda: 2_000.0)
    _write_uptime(tmp_path, uptime_seconds=1_000.0)
    monkeypatch.setattr(
        "sandcastle_dashboard.discovery._clock_ticks_per_second", lambda: 100.0
    )
    _write_process(
        tmp_path,
        pid=40,
        ppid=1,
        argv=["node", ".sandcastle/main.mts"],
        starttime_ticks=500,
    )

    groups = discover_host_run_processes(tmp_path)

    # boot epoch = 2000 - 1000 = 1000; started_at = 1000 + 500/100 = 1005
    assert groups[0].started_at == pytest.approx(1005.0)


def test_discover_host_run_processes_orders_newer_orchestrator_after_older_one(
    tmp_path,
):
    _write_uptime(tmp_path)
    _write_process(
        tmp_path,
        pid=50,
        ppid=1,
        argv=["node", ".sandcastle/main.mts"],
        starttime_ticks=100,
    )
    _write_process(
        tmp_path,
        pid=51,
        ppid=1,
        argv=["node", ".sandcastle/main.mts"],
        starttime_ticks=200,
    )

    groups = discover_host_run_processes(tmp_path)
    started_at_by_pid = {group.pid: group.started_at for group in groups}

    assert started_at_by_pid[51] > started_at_by_pid[50]


def test_discover_host_run_processes_ignores_a_pid_directory_missing_its_stat_file(
    tmp_path,
):
    _write_uptime(tmp_path)
    _write_process(tmp_path, pid=60, ppid=1, argv=["node", ".sandcastle/main.mts"])
    broken_dir = tmp_path / "61"
    broken_dir.mkdir()
    # no stat/cmdline files written: simulates a process that vanished mid-scan

    groups = discover_host_run_processes(tmp_path)

    assert len(groups) == 1
    assert groups[0].pid == 60


def test_discover_host_run_processes_ignores_unreadable_stat_file(
    tmp_path, monkeypatch
):
    _write_uptime(tmp_path)
    _write_process(tmp_path, pid=70, ppid=1, argv=["node", ".sandcastle/main.mts"])

    real_read_text = Path.read_text

    def _flaky_read_text(self, *args, **kwargs):
        if self.name == "stat" and self.parent.name == "70":
            raise OSError("process vanished")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _flaky_read_text)

    groups = discover_host_run_processes(tmp_path)

    assert groups == []


def test_discover_host_run_processes_ignores_non_numeric_proc_entries(tmp_path):
    _write_uptime(tmp_path)
    (tmp_path / "self").mkdir()
    (tmp_path / "net").mkdir()
    _write_process(tmp_path, pid=80, ppid=1, argv=["node", ".sandcastle/main.mts"])

    groups = discover_host_run_processes(tmp_path)

    assert len(groups) == 1
    assert groups[0].pid == 80


def test_discover_host_run_processes_reads_explicit_invocation_and_deployment_ids(
    tmp_path,
):
    _write_uptime(tmp_path)
    _write_process(
        tmp_path,
        pid=90,
        ppid=1,
        argv=["node", ".sandcastle/main.mts"],
        environ={
            "SANDCASTLE_INVOCATION_ID": "inv-123",
            "SANDCASTLE_DEPLOYMENT_ID": "deploy-1",
            "PATH": "/usr/bin",
        },
    )

    groups = discover_host_run_processes(tmp_path)

    assert len(groups) == 1
    assert groups[0].invocation_id == "inv-123"
    assert groups[0].deployment_id == "deploy-1"


def test_discover_host_run_processes_leaves_ids_unset_without_explicit_env(tmp_path):
    _write_uptime(tmp_path)
    _write_process(tmp_path, pid=91, ppid=1, argv=["node", ".sandcastle/main.mts"])

    groups = discover_host_run_processes(tmp_path)

    assert len(groups) == 1
    assert groups[0].invocation_id is None
    assert groups[0].deployment_id is None


def test_discover_host_run_processes_returns_empty_when_proc_root_is_unreadable(
    tmp_path,
):
    missing_root = tmp_path / "does-not-exist"

    groups = discover_host_run_processes(missing_root)

    assert groups == []


def test_discover_host_run_processes_aggregates_cpu_seconds_across_the_tree(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "sandcastle_dashboard.discovery._clock_ticks_per_second", lambda: 100.0
    )
    _write_uptime(tmp_path)
    _write_process(
        tmp_path,
        pid=90,
        ppid=1,
        argv=["node", ".sandcastle/main.mts"],
        utime_ticks=50,
        stime_ticks=30,
    )
    _write_process(
        tmp_path,
        pid=91,
        ppid=90,
        argv=["sbx", "exec", "claude"],
        utime_ticks=20,
        stime_ticks=10,
    )

    groups = discover_host_run_processes(tmp_path)

    assert len(groups) == 1
    # (50 + 30 + 20 + 10) ticks / 100 ticks-per-second
    assert groups[0].cpu_seconds == pytest.approx(1.1)


def test_discover_host_run_processes_aggregates_resident_memory_across_the_tree(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("sandcastle_dashboard.discovery._page_size", lambda: 4096)
    _write_uptime(tmp_path)
    _write_process(
        tmp_path, pid=92, ppid=1, argv=["node", ".sandcastle/main.mts"], rss_pages=100
    )
    _write_process(
        tmp_path, pid=93, ppid=92, argv=["sbx", "exec", "claude"], rss_pages=50
    )

    groups = discover_host_run_processes(tmp_path)

    assert len(groups) == 1
    assert groups[0].memory_bytes == 150 * 4096


def test_discover_host_run_processes_sets_a_monotonic_sampled_at_timestamp(
    tmp_path, monkeypatch
):
    monkeypatch.setattr("sandcastle_dashboard.discovery.time.monotonic", lambda: 42.0)
    _write_uptime(tmp_path)
    _write_process(tmp_path, pid=94, ppid=1, argv=["node", ".sandcastle/main.mts"])

    groups = discover_host_run_processes(tmp_path)

    assert groups[0].sampled_at == 42.0


def test_discover_host_run_processes_defaults_cpu_and_memory_when_stat_omits_them(
    tmp_path,
):
    """A stat line shorter than the optional cpu/rss fields must not crash
    discovery: those fields default to zero rather than the process itself
    being dropped."""
    _write_uptime(tmp_path)
    pid_dir = tmp_path / "97"
    pid_dir.mkdir()
    # Only state, ppid, and starttime are present; utime/stime/rss are absent.
    fields = ["S", "1"] + ["0"] * 17 + ["100"]
    (pid_dir / "stat").write_text("97 (node) " + " ".join(fields))
    (pid_dir / "cmdline").write_bytes(b"node\x00.sandcastle/main.mts\x00")

    groups = discover_host_run_processes(tmp_path)

    assert len(groups) == 1
    assert groups[0].cpu_seconds == 0.0
    assert groups[0].memory_bytes == 0
