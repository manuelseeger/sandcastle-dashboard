"""Unit tests for deriving each Castle's branch from Sandcastle naming
conventions verified against the Run Repository's local Git branches.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from sandcastle_dashboard.branch_identity import (
    attach_branches,
    candidate_branch,
    list_local_branches,
)
from sandcastle_dashboard.snapshot import Castle, HostRun, Repository


def _fake_branch_runner(returncode: int, stdout: str):
    def runner(cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[], returncode=returncode, stdout=stdout, stderr=""
        )

    return runner


def test_list_local_branches_returns_branch_names_from_git_output():
    runner = _fake_branch_runner(0, "main\nsandcastle/issue-9\n")

    branches = list_local_branches("/repo", run=runner)

    assert branches == frozenset({"main", "sandcastle/issue-9"})


def test_list_local_branches_returns_empty_set_when_git_reports_failure():
    runner = _fake_branch_runner(128, "")

    branches = list_local_branches("/repo", run=runner)

    assert branches == frozenset()


def test_list_local_branches_returns_empty_set_when_running_git_raises():
    def runner(cwd: Path) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git not installed")

    branches = list_local_branches("/repo", run=runner)

    assert branches == frozenset()


def test_candidate_branch_derives_sandcastle_issue_branch_for_an_issue_castle():
    castle = Castle(
        name="c1",
        host_run_id="run-1",
        scope="issue",
        vm_state="running",
        issue_number=9,
    )

    assert candidate_branch(castle) == "sandcastle/issue-9"


def test_candidate_branch_derives_root_branch_for_a_merger_castle():
    castle = Castle(
        name="c1",
        host_run_id="run-1",
        scope="merger",
        vm_state="running",
        root_number=7,
    )

    assert candidate_branch(castle) == "sandcastle/issue-7"


def test_candidate_branch_is_none_for_a_planner_castle():
    castle = Castle(name="c1", host_run_id="run-1", scope="planner", vm_state="running")

    assert candidate_branch(castle) is None


def test_attach_branches_sets_branch_when_the_candidate_exists_in_the_repository():
    host_run = HostRun(
        id="run-1", pid=1, repository=Repository(path="/repo", name="repo")
    )
    castle = Castle(
        name="c1",
        host_run_id="run-1",
        scope="issue",
        vm_state="running",
        issue_number=9,
    )

    resolved = attach_branches(
        [castle],
        [host_run],
        list_branches=lambda path: frozenset({"sandcastle/issue-9"}),
    )

    assert resolved[0].branch == "sandcastle/issue-9"


def test_attach_branches_leaves_branch_unset_when_the_candidate_branch_is_missing():
    host_run = HostRun(
        id="run-1", pid=1, repository=Repository(path="/repo", name="repo")
    )
    castle = Castle(
        name="c1",
        host_run_id="run-1",
        scope="issue",
        vm_state="running",
        issue_number=9,
    )

    resolved = attach_branches(
        [castle], [host_run], list_branches=lambda path: frozenset()
    )

    assert resolved[0].branch is None


def test_attach_branches_leaves_branch_unset_when_the_host_run_has_no_repository():
    host_run = HostRun(id="run-1", pid=1, repository=None)
    castle = Castle(
        name="c1",
        host_run_id="run-1",
        scope="issue",
        vm_state="running",
        issue_number=9,
    )

    calls = []
    resolved = attach_branches(
        [castle],
        [host_run],
        list_branches=lambda path: calls.append(path) or frozenset(),
    )

    assert resolved[0].branch is None
    assert calls == []


def test_attach_branches_leaves_branch_unset_for_a_planner_castle():
    host_run = HostRun(
        id="run-1", pid=1, repository=Repository(path="/repo", name="repo")
    )
    castle = Castle(name="c1", host_run_id="run-1", scope="planner", vm_state="running")

    resolved = attach_branches(
        [castle],
        [host_run],
        list_branches=lambda path: frozenset({"sandcastle/issue-9"}),
    )

    assert resolved[0].branch is None


def test_attach_branches_leaves_branch_unset_when_the_castle_has_no_matching_host_run():
    castle = Castle(
        name="c1",
        host_run_id="missing-run",
        scope="issue",
        vm_state="running",
        issue_number=9,
    )

    resolved = attach_branches(
        [castle], [], list_branches=lambda path: frozenset({"sandcastle/issue-9"})
    )

    assert resolved[0].branch is None


def test_attach_branches_only_looks_up_branches_once_per_repository():
    host_run_a = HostRun(
        id="run-1", pid=1, repository=Repository(path="/repo", name="repo")
    )
    host_run_b = HostRun(
        id="run-2", pid=2, repository=Repository(path="/repo", name="repo")
    )
    castles = (
        Castle(
            name="c1",
            host_run_id="run-1",
            scope="issue",
            vm_state="running",
            issue_number=9,
        ),
        Castle(
            name="c2",
            host_run_id="run-2",
            scope="issue",
            vm_state="running",
            issue_number=3,
        ),
    )
    calls = []

    def list_branches(path: str) -> frozenset[str]:
        calls.append(path)
        return frozenset({"sandcastle/issue-9", "sandcastle/issue-3"})

    resolved = attach_branches(
        castles, [host_run_a, host_run_b], list_branches=list_branches
    )

    assert [castle.branch for castle in resolved] == [
        "sandcastle/issue-9",
        "sandcastle/issue-3",
    ]
    assert calls == ["/repo"]
