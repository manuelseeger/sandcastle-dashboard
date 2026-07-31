"""Derives each Castle's branch from Sandcastle naming conventions, verified
against the Run Repository's local Git branches.

Issue and merger Castles imply the documented ``sandcastle/issue-<id>``
branch. That name is only attached to a Castle when a Git branch with the
exact same name exists in its Host Run's Run Repository: the naming
convention alone is not proof the branch is still present, and a Castle
whose Host Run or repository is unknown gets no invented branch.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path

from sandcastle_dashboard.snapshot import Castle, HostRun

BranchRunner = Callable[[Path], "subprocess.CompletedProcess[str]"]


def run_git_local_branches(cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run ``git for-each-ref`` to list local branch names in ``cwd``."""
    return subprocess.run(
        [
            "git",
            "-C",
            str(cwd),
            "for-each-ref",
            "--format=%(refname:short)",
            "refs/heads",
        ],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def list_local_branches(
    repository_path: str, *, run: BranchRunner = run_git_local_branches
) -> frozenset[str]:
    """Return the Run Repository's local branch names.

    Returns an empty set when ``git`` cannot be run or reports failure,
    rather than raising.
    """
    try:
        result = run(Path(repository_path))
    except OSError, subprocess.SubprocessError:
        return frozenset()
    if result.returncode != 0:
        return frozenset()
    return frozenset(
        line.strip() for line in result.stdout.splitlines() if line.strip()
    )


def candidate_branch(castle: Castle) -> str | None:
    """The branch Sandcastle's naming convention implies for ``castle``.

    Returns ``None`` for planner Castles and any Castle whose scope number
    could not be parsed, since no convention derives their branch.
    """
    if castle.scope == "issue" and castle.issue_number is not None:
        return f"sandcastle/issue-{castle.issue_number}"
    if castle.scope == "merger" and castle.root_number is not None:
        return f"sandcastle/issue-{castle.root_number}"
    return None


def attach_branches(
    castles: Sequence[Castle],
    host_runs: Sequence[HostRun],
    *,
    list_branches: Callable[[str], frozenset[str]] = list_local_branches,
) -> tuple[Castle, ...]:
    """Attach a Git-verified branch to each Castle.

    A Castle keeps ``branch=None`` when its Host Run or repository is
    unknown, its scope has no naming-convention branch, or the candidate
    branch does not exist in the Run Repository.
    """
    repositories_by_host_run = {run.id: run.repository for run in host_runs}
    branches_by_repository: dict[str, frozenset[str]] = {}
    resolved = []
    for castle in castles:
        branch = None
        candidate = candidate_branch(castle)
        repository = repositories_by_host_run.get(castle.host_run_id)
        if candidate is not None and repository is not None:
            if repository.path not in branches_by_repository:
                branches_by_repository[repository.path] = list_branches(repository.path)
            if candidate in branches_by_repository[repository.path]:
                branch = candidate
        resolved.append(replace(castle, branch=branch))
    return tuple(resolved)
