"""Unit tests for deriving the Run Repository from a process cwd."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sandcastle_dashboard.repository import resolve_repository
from sandcastle_dashboard.snapshot import Repository


def _fake_runner(returncode: int, stdout: str):
    def runner(cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            returncode=returncode,
            stdout=stdout,
            stderr="",
        )

    return runner


def test_resolve_repository_returns_repository_from_git_toplevel_output():
    runner = _fake_runner(0, "/home/agent/workspace\n")

    repository = resolve_repository(Path("/home/agent/workspace/sub"), run=runner)

    assert repository == Repository(path="/home/agent/workspace", name="workspace")


def test_resolve_repository_returns_none_when_cwd_is_unknown():
    calls = []

    def runner(cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(cwd)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

    repository = resolve_repository(None, run=runner)

    assert repository is None
    assert calls == []


def test_resolve_repository_returns_none_when_git_reports_failure():
    runner = _fake_runner(128, "")

    repository = resolve_repository(Path("/tmp"), run=runner)

    assert repository is None


def test_resolve_repository_returns_none_when_git_output_is_blank():
    runner = _fake_runner(0, "\n")

    repository = resolve_repository(Path("/tmp"), run=runner)

    assert repository is None


def test_resolve_repository_returns_none_when_running_git_raises():
    def runner(cwd: Path) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git not installed")

    repository = resolve_repository(Path("/tmp"), run=runner)

    assert repository is None


def test_resolve_repository_returns_none_when_git_times_out():
    def runner(cwd: Path) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd="git", timeout=5)

    repository = resolve_repository(Path("/tmp"), run=runner)

    assert repository is None
