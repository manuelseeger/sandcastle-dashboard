"""Selects, segments, and bounds a Castle's current-phase role log.

Sandcastle role logs under ``.sandcastle/logs/`` are reused across
invocations: a log file's existence does not mean the current phase is
running, and appended output from a previous invocation must not be
shown as current work. This module identifies the log file relevant to
a Castle's phase, isolates the latest ``Run started`` segment within
it, and returns only a bounded tail. Raw log content returned here is
held in memory by the caller only; nothing here writes it back out.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from sandcastle_dashboard.snapshot import Castle

_RUN_STARTED_RE = re.compile(r"Run started")

_DEFAULT_MAX_BYTES = 65536
_DEFAULT_MAX_LINES = 200


@dataclass(frozen=True, slots=True)
class LogSelection:
    """The inferred phase for a Castle plus its bounded current-run tail."""

    phase: str
    last_activity_at: float | None = None
    log_tail: tuple[str, ...] = field(default_factory=tuple)


def latest_run_segment(text: str) -> str:
    """Return only the content from the latest `Run started` marker onward.

    Returns ``text`` unchanged when no marker is present, which is also
    correct when a bounded read already starts after the true last
    marker: everything in that window already belongs to the latest run.
    """
    lines = text.splitlines()
    last_marker_index = None
    for index, line in enumerate(lines):
        if _RUN_STARTED_RE.search(line):
            last_marker_index = index
    if last_marker_index is None:
        return text
    return "\n".join(lines[last_marker_index:])


def tail_lines(text: str, max_lines: int) -> list[str]:
    """Return the newest ``max_lines`` lines of ``text``."""
    if max_lines <= 0:
        return []
    return text.splitlines()[-max_lines:]


def read_bounded_tail(path: Path, max_bytes: int = _DEFAULT_MAX_BYTES) -> str:
    """Read only the trailing ``max_bytes`` of ``path``, decoded to text.

    Returns an empty string when the file cannot be read. A possibly
    partial first line from seeking into the middle of the file is
    discarded.
    """
    try:
        size = path.stat().st_size
    except OSError:
        return ""
    try:
        with path.open("rb") as handle:
            truncated = size > max_bytes
            if truncated:
                handle.seek(size - max_bytes)
            data = handle.read()
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace")
    if truncated:
        _, _, text = text.partition("\n")
    return text


def _newest(paths: Iterable[Path]) -> Path | None:
    candidates = list(paths)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def select_role_log(logs_dir: Path, castle: Castle) -> tuple[Path | None, str]:
    """Select the log file for a Castle's current phase.

    Planner and merger Castles use their scope-appropriate log. Issue
    Castles choose whichever of the implementer or reviewer log was
    most recently active, reporting ``provisioning`` before either
    exists.
    """
    if not logs_dir.is_dir():
        return None, "provisioning" if castle.scope == "issue" else castle.scope

    if castle.scope == "planner":
        return (
            _newest(
                [
                    *logs_dir.glob("*-planner.log"),
                    *logs_dir.glob("*-picker-*.log"),
                ]
            ),
            "planner",
        )

    if castle.scope == "merger":
        path = None
        if castle.scope_id is not None:
            path = _newest(
                logs_dir.glob(f"sandcastle-issue-{castle.scope_id}-merger-*.log")
            )
        return path, "merger"

    if castle.scope == "issue":
        if castle.issue_number is None:
            return None, "provisioning"
        candidates = [
            (
                role,
                _newest(logs_dir.glob(f"*-issue-{castle.issue_number}-{role}-*.log")),
            )
            for role in ("implementer", "reviewer")
        ]
        active = [(role, path) for role, path in candidates if path is not None]
        if not active:
            return None, "provisioning"
        role, path = max(active, key=lambda item: item[1].stat().st_mtime)
        return path, role

    return None, castle.scope


def resolve_castle_log(
    logs_dir: Path,
    castle: Castle,
    *,
    max_bytes: int = _DEFAULT_MAX_BYTES,
    max_lines: int = _DEFAULT_MAX_LINES,
) -> LogSelection:
    """Resolve a Castle's phase, last-activity time, and bounded log tail."""
    path, phase = select_role_log(logs_dir, castle)
    if path is None:
        return LogSelection(phase=phase)
    try:
        last_activity_at = path.stat().st_mtime
    except OSError:
        return LogSelection(phase=phase)
    text = read_bounded_tail(path, max_bytes=max_bytes)
    segment = latest_run_segment(text)
    return LogSelection(
        phase=phase,
        last_activity_at=last_activity_at,
        log_tail=tuple(tail_lines(segment, max_lines)),
    )
