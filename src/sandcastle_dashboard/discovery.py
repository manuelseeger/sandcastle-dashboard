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

# The only environment keys discovery ever reads, and only for the
# orchestrator process. These carry explicit Sandcastle correlation
# identifiers; no other environment key or full command line is retained.
INVOCATION_ID_ENV_KEY = "SANDCASTLE_INVOCATION_ID"
DEPLOYMENT_ID_ENV_KEY = "SANDCASTLE_DEPLOYMENT_ID"
_ALLOWLISTED_ENV_KEYS = frozenset({INVOCATION_ID_ENV_KEY, DEPLOYMENT_ID_ENV_KEY})

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
    cpu_ticks: int
    memory_bytes: int
    invocation_id: str | None = None
    deployment_id: str | None = None


@dataclass(frozen=True, slots=True)
class HostRunProcessGroup:
    """One orchestration Node process and the pids grouped under it."""

    pid: int
    member_pids: frozenset[int]
    cwd: Path | None
    started_at: float | None
    process_state: str
    cpu_seconds: float
    memory_bytes: int
    sampled_at: float
    invocation_id: str | None = None
    deployment_id: str | None = None


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
    sampled_at = time.monotonic()

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
        cpu_ticks_total = sum(processes[pid].cpu_ticks for pid in members)
        memory_bytes_total = sum(processes[pid].memory_bytes for pid in members)
        groups.append(
            HostRunProcessGroup(
                pid=record.pid,
                member_pids=frozenset(members),
                cwd=record.cwd,
                started_at=started_at,
                process_state=record.process_state,
                cpu_seconds=cpu_ticks_total / clock_ticks_per_second,
                memory_bytes=memory_bytes_total,
                sampled_at=sampled_at,
                invocation_id=record.invocation_id,
                deployment_id=record.deployment_id,
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
    ppid, state_code, starttime_ticks, utime_ticks, stime_ticks, rss_pages = parsed
    argv = _read_cmdline(pid_dir)
    role = _classify(argv)
    cwd = _read_cwd(pid_dir)
    invocation_id = None
    deployment_id = None
    if role == "orchestrator":
        allowlisted_env = _read_allowlisted_env(pid_dir)
        invocation_id = allowlisted_env.get(INVOCATION_ID_ENV_KEY)
        deployment_id = allowlisted_env.get(DEPLOYMENT_ID_ENV_KEY)
    return ProcessRecord(
        pid=pid,
        ppid=ppid,
        role=role,
        process_state=_PROCESS_STATE_LABELS.get(state_code, "unknown"),
        starttime_ticks=starttime_ticks,
        cwd=cwd,
        cpu_ticks=utime_ticks + stime_ticks,
        memory_bytes=rss_pages * _page_size(),
        invocation_id=invocation_id,
        deployment_id=deployment_id,
    )


def _parse_stat(text: str) -> tuple[int, str, int, int, int, int] | None:
    try:
        last_paren = text.rindex(")")
    except ValueError:
        return None
    rest = text[last_paren + 2 :].split()
    try:
        state = rest[0]
        ppid = int(rest[1])
        starttime_ticks = int(rest[19])
    except IndexError, ValueError:
        return None
    utime_ticks = _int_field(rest, 11)
    stime_ticks = _int_field(rest, 12)
    rss_pages = _int_field(rest, 21)
    return ppid, state, starttime_ticks, utime_ticks, stime_ticks, rss_pages


def _int_field(fields: list[str], index: int) -> int:
    try:
        return int(fields[index])
    except IndexError, ValueError:
        return 0


def _read_cmdline(pid_dir: Path) -> list[str]:
    try:
        raw = (pid_dir / "cmdline").read_bytes()
    except OSError:
        return []
    return [
        part.decode("utf-8", errors="replace") for part in raw.split(b"\x00") if part
    ]


def _read_allowlisted_env(pid_dir: Path) -> dict[str, str]:
    """Read only ``_ALLOWLISTED_ENV_KEYS`` from a process's environment.

    The full environment is never parsed into a dict or retained: each entry
    is checked against the allowlist as it is read, and everything else is
    discarded immediately.
    """
    try:
        raw = (pid_dir / "environ").read_bytes()
    except OSError:
        return {}
    found: dict[str, str] = {}
    for entry in raw.split(b"\x00"):
        if not entry or b"=" not in entry:
            continue
        key, _, value = entry.partition(b"=")
        key_text = key.decode("utf-8", errors="replace")
        if key_text in _ALLOWLISTED_ENV_KEYS:
            found[key_text] = value.decode("utf-8", errors="replace")
    return found


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
    except OSError, ValueError, IndexError:
        return None
    return time.time() - uptime_seconds


def _clock_ticks_per_second() -> float:
    try:
        return float(os.sysconf("SC_CLK_TCK"))
    except AttributeError, ValueError, OSError:
        return 100.0


def _page_size() -> int:
    try:
        return int(os.sysconf("SC_PAGESIZE"))
    except AttributeError, ValueError, OSError:
        return 4096
