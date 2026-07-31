"""Behavior tests proving discovery never retains or renders unrelated
command-line or environment values.

Process command lines can carry injected credential values, so discovery
must read only allowlisted identification fields and must never store or
expose full command lines or process environments.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from sandcastle_dashboard.discovery import ProcessRecord, discover_host_run_processes
from sandcastle_dashboard.live_snapshot_provider import LiveHostRunSnapshotProvider
from sandcastle_dashboard.logs import resolve_castle_log
from sandcastle_dashboard.snapshot import Castle

SECRET = "super-secret-token-do-not-leak"


def _write_stat(pid_dir: Path, pid: int, ppid: int, state: str = "S") -> None:
    fields = ["0"] * 22
    fields[0] = state
    fields[1] = str(ppid)
    fields[19] = "100"
    (pid_dir / "stat").write_text(f"{pid} (node) " + " ".join(fields))


def _write_orchestrator_with_secret_cmdline(
    proc_root: Path, pid: int, cwd: Path
) -> None:
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir()
    _write_stat(pid_dir, pid, ppid=1)
    argv = ["node", ".sandcastle/main.mts", f"--auth-token={SECRET}"]
    (pid_dir / "cmdline").write_bytes(b"\x00".join(a.encode() for a in argv) + b"\x00")
    (pid_dir / "cwd").symlink_to(cwd)
    (pid_dir / "environ").write_bytes(f"SANDCASTLE_SECRET={SECRET}\x00".encode())


def _write_uptime(proc_root: Path) -> None:
    (proc_root / "uptime").write_text("1000.0 900.0\n")


def test_process_record_has_no_field_that_could_carry_a_raw_command_line_or_environment():
    field_names = {field.name for field in dataclasses.fields(ProcessRecord)}

    assert "cmdline" not in field_names
    assert "argv" not in field_names
    assert "environ" not in field_names
    assert "env" not in field_names


def test_discovered_host_run_process_group_never_contains_the_secret_cmdline_value(
    tmp_path,
):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _write_uptime(proc_root)
    _write_orchestrator_with_secret_cmdline(proc_root, pid=42, cwd=repo_dir)

    groups = discover_host_run_processes(proc_root)

    assert len(groups) == 1
    assert SECRET not in repr(groups[0])
    assert SECRET not in str(groups[0])


def test_snapshot_pipeline_excludes_secret_cmdline_and_environment_values(tmp_path):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _write_uptime(proc_root)
    _write_orchestrator_with_secret_cmdline(proc_root, pid=42, cwd=repo_dir)

    def git_runner(cwd):
        import subprocess

        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=f"{repo_dir}\n", stderr=""
        )

    provider = LiveHostRunSnapshotProvider(proc_root=proc_root, git_runner=git_runner)

    snapshot = provider.get_snapshot()

    assert len(snapshot.host_runs) == 1
    assert SECRET not in repr(snapshot)
    assert SECRET not in str(snapshot)


def test_discovery_never_retains_unallowlisted_environment_values(tmp_path):
    """Discovery may read the orchestrator's environ to extract explicit
    Sandcastle correlation identifiers, but only the two allowlisted keys —
    every other environment value, such as an injected secret, must never
    surface on the resulting process group."""
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _write_uptime(proc_root)
    _write_orchestrator_with_secret_cmdline(proc_root, pid=42, cwd=repo_dir)

    groups = discover_host_run_processes(proc_root)

    assert len(groups) == 1
    assert SECRET not in repr(groups[0])
    assert SECRET not in str(groups[0])
    assert groups[0].invocation_id is None
    assert groups[0].deployment_id is None


def test_discovery_never_reads_environ_for_non_orchestrator_processes(
    tmp_path, monkeypatch
):
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    _write_uptime(proc_root)
    _write_orchestrator_with_secret_cmdline(proc_root, pid=42, cwd=repo_dir)
    wrapper_dir = proc_root / "41"
    wrapper_dir.mkdir()
    _write_stat(wrapper_dir, pid=41, ppid=1)
    (wrapper_dir / "cmdline").write_bytes(b"npm\x00run\x00sandcastle\x00")
    (wrapper_dir / "environ").write_bytes(f"SANDCASTLE_SECRET={SECRET}\x00".encode())

    real_read_bytes = Path.read_bytes

    def _guarded_read_bytes(self, *args, **kwargs):
        if self.name == "environ" and self.parent.name != "42":
            pytest.fail(f"discovery must never read {self}")
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", _guarded_read_bytes)

    groups = discover_host_run_processes(proc_root)

    assert len(groups) == 1


def test_resolving_a_castle_log_never_writes_a_copy_of_its_content_to_disk(tmp_path):
    """Raw log content is sensitive and must stay in memory only; reading it
    for display must never create a persisted copy anywhere on disk."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    log_path = logs_dir / "sandcastle-issue-9-implementer-9.log"
    log_path.write_text(f"Run started 10:00\n{SECRET}\n")
    castle = Castle(
        name="parames-prod-9-issue-9-abc",
        host_run_id="run-1",
        scope="issue",
        issue_number=9,
        vm_state="running",
    )
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))

    selection = resolve_castle_log(logs_dir, castle)

    assert SECRET in selection.log_tail[-1]
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    assert after == before
