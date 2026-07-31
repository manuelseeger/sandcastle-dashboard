"""Discovers Sandcastle orchestration process groups from ``/proc``.

Identifies the orchestration Node process by allowlisted executable and
script markers, then groups its known npm/tsx wrapper ancestors and all of
its descendants under that Node PID so a wrapper hierarchy is represented as
one Host Run rather than duplicate ones.

Only fields needed for identification and display are read. Full command
lines and environments are never retained: command-line tokens are consulted
transiently to classify a process's role and are discarded immediately
afterward.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ORCHESTRATOR_SCRIPT_SUFFIXES = (".sandcastle/main.mts",)
WRAPPER_EXECUTABLE_NAMES = frozenset({"npm", "tsx"})

_PROCESS_STATE_LABELS = {
    "R": "running",
    "S": "sleeping",
    "D": "disk-sleep",
    "Z": "zombie",
    "T": "stopped",
    "t": "tracing-stop",
    "X": "dead",
    "I": "idle",
}

_MAX_WRAPPER_ANCESTOR_HOPS = 10


@dataclass(frozen=True, slots=True)
class ProcessRecord:
    """Allowlisted identification fields read for one live process."""

    pid: int
    ppid: int
    role: str
    process_state: str
    starttime_ticks: int
    cwd: Path | None


@dataclass(frozen=True, slots=True)
class HostRunProcessGroup:
    """One orchestration Node process and the pids grouped under it."""

    pid: int
    member_pids: frozenset[int]
    cwd: Path | None
    started_at: float | None
    process_state: str


def discover_host_run_processes(
    proc_root: Path = Path("/proc"),
) -> list[HostRunProcessGroup]:
    """Discover Host Run process groups from ``proc_root``.

    Vanishing or unreadable process entries are skipped rather than raising,
    so a racing process table never crashes discovery.
    """
    processes = _read_all_processes(proc_root)
    boot_epoch = _boot_epoch(proc_root)
    clock_ticks_per_second = _clock_ticks_per_second()

    children_by_ppid: dict[int, list[int]] = defaultdict(list)
    for record in processes.values():
        children_by_ppid[record.ppid].append(record.pid)

    groups = []
    for record in processes.values():
        if record.role != "orchestrator":
            continue
        members = {record.pid}
        members |= _collect_descendants(record.pid, children_by_ppid)
        members |= _collect_wrapper_ancestors(record, processes)
        started_at = (
            boot_epoch + record.starttime_ticks / clock_ticks_per_second
            if boot_epoch is not None
            else None
        )
        groups.append(
            HostRunProcessGroup(
                pid=record.pid,
                member_pids=frozenset(members),
                cwd=record.cwd,
                started_at=started_at,
                process_state=record.process_state,
            )
        )
    return groups


def _collect_descendants(pid: int, children_by_ppid: dict[int, list[int]]) -> set[int]:
    descendants: set[int] = set()
    frontier = [pid]
    while frontier:
        current = frontier.pop()
        for child in children_by_ppid.get(current, ()):
            if child in descendants or child == pid:
                continue
            descendants.add(child)
            frontier.append(child)
    return descendants


def _collect_wrapper_ancestors(
    record: ProcessRecord, processes: dict[int, ProcessRecord]
) -> set[int]:
    ancestors: set[int] = set()
    current_ppid = record.ppid
    for _ in range(_MAX_WRAPPER_ANCESTOR_HOPS):
        parent = processes.get(current_ppid)
        if parent is None or parent.role != "wrapper":
            break
        ancestors.add(parent.pid)
        current_ppid = parent.ppid
    return ancestors


def _read_all_processes(proc_root: Path) -> dict[int, ProcessRecord]:
    processes: dict[int, ProcessRecord] = {}
    try:
        entries = list(proc_root.iterdir())
    except OSError:
        return processes
    for entry in entries:
        if not entry.name.isdigit():
            continue
        record = _read_process(entry)
        if record is not None:
            processes[record.pid] = record
    return processes


def _read_process(pid_dir: Path) -> ProcessRecord | None:
    try:
        pid = int(pid_dir.name)
    except ValueError:
        return None
    try:
        stat_text = (pid_dir / "stat").read_text()
    except OSError:
        return None
    parsed = _parse_stat(stat_text)
    if parsed is None:
        return None
    ppid, state_code, starttime_ticks = parsed
    argv = _read_cmdline(pid_dir)
    role = _classify(argv)
    cwd = _read_cwd(pid_dir)
    return ProcessRecord(
        pid=pid,
        ppid=ppid,
        role=role,
        process_state=_PROCESS_STATE_LABELS.get(state_code, "unknown"),
        starttime_ticks=starttime_ticks,
        cwd=cwd,
    )


def _parse_stat(text: str) -> tuple[int, str, int] | None:
    try:
        last_paren = text.rindex(")")
    except ValueError:
        return None
    rest = text[last_paren + 2 :].split()
    try:
        state = rest[0]
        ppid = int(rest[1])
        starttime_ticks = int(rest[19])
    except (IndexError, ValueError):
        return None
    return ppid, state, starttime_ticks


def _read_cmdline(pid_dir: Path) -> list[str]:
    try:
        raw = (pid_dir / "cmdline").read_bytes()
    except OSError:
        return []
    return [
        part.decode("utf-8", errors="replace") for part in raw.split(b"\x00") if part
    ]


def _read_cwd(pid_dir: Path) -> Path | None:
    try:
        target = os.readlink(pid_dir / "cwd")
    except OSError:
        return None
    return Path(target)


def _classify(argv: list[str]) -> str:
    if not argv:
        return "other"
    exe_name = Path(argv[0]).name
    if exe_name in WRAPPER_EXECUTABLE_NAMES:
        return "wrapper"
    if exe_name != "node":
        return "other"
    tail = argv[1:]
    for token in tail:
        if any(token.endswith(suffix) for suffix in ORCHESTRATOR_SCRIPT_SUFFIXES):
            return "orchestrator"
    for token in tail:
        if Path(token).name in WRAPPER_EXECUTABLE_NAMES:
            return "wrapper"
    return "other"


def _boot_epoch(proc_root: Path) -> float | None:
    try:
        uptime_seconds = float((proc_root / "uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return time.time() - uptime_seconds


def _clock_ticks_per_second() -> float:
    try:
        return float(os.sysconf("SC_CLK_TCK"))
    except (AttributeError, ValueError, OSError):
        return 100.0
