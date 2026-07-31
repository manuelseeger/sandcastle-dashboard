"""Derives a Host Run's Run Repository from its process working directory."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from sandcastle_dashboard.snapshot import Repository

GitRunner = Callable[[Path], "subprocess.CompletedProcess[str]"]


def run_git_toplevel(cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run ``git rev-parse --show-toplevel`` in ``cwd``."""
    return subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def resolve_repository(
    cwd: Path | None, *, run: GitRunner = run_git_toplevel
) -> Repository | None:
    """Derive the Run Repository from a process working directory.

    Returns ``None`` when ``cwd`` is unknown, is not inside a Git
    repository, or the ``git`` command cannot be run.
    """
    if cwd is None:
        return None
    try:
        result = run(cwd)
    except OSError, subprocess.SubprocessError:
        return None
    if result.returncode != 0:
        return None
    toplevel = result.stdout.strip()
    if not toplevel:
        return None
    return Repository(path=toplevel, name=Path(toplevel).name)
