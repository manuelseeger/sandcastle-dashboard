"""Discovers and inspects running Castles through the `sbx` JSON CLI.

Only running Castles are inspected: a stopped Castle must never appear in
the dashboard. Missing `sbx`, malformed JSON, and per-Castle inspection
failures are reported as a readable error without discarding whatever
Castles were still successfully inspected.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

SbxRunner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]

_RUNNING_STATUS = "running"


def run_sbx(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run the real `sbx` CLI with the given arguments."""
    return subprocess.run(
        ["sbx", *args], capture_output=True, text=True, timeout=10, check=False
    )


@dataclass(frozen=True, slots=True)
class CastleInspection:
    """Fields read from `sbx inspect --json` for one running Castle."""

    name: str
    vm_state: str
    uptime_seconds: float | None = None
    session_count: int | None = None


@dataclass(frozen=True, slots=True)
class CastleDiscoveryResult:
    """Running Castle inspections plus a readable error, if any occurred."""

    castles: tuple[CastleInspection, ...] = ()
    error: str | None = None


def discover_running_castles(run: SbxRunner = run_sbx) -> CastleDiscoveryResult:
    """Discover and inspect every currently running Castle."""
    names, list_error = _list_running_castle_names(run)
    if list_error is not None:
        return CastleDiscoveryResult(castles=(), error=list_error)

    castles: list[CastleInspection] = []
    errors: list[str] = []
    for name in names:
        inspection, inspect_error = _inspect_castle(name, run)
        if inspection is not None:
            castles.append(inspection)
        if inspect_error is not None:
            errors.append(inspect_error)
    return CastleDiscoveryResult(
        castles=tuple(castles), error="; ".join(errors) if errors else None
    )


def _run_json_command(
    args: Sequence[str], run: SbxRunner
) -> tuple[object | None, str | None]:
    command = " ".join(["sbx", *args])
    try:
        result = run(args)
    except FileNotFoundError:
        return None, "sbx is not installed or not on PATH"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"Failed to run {command}: {exc}"
    if result.returncode != 0:
        message = result.stderr.strip() or f"exit code {result.returncode}"
        return None, f"{command} failed: {message}"
    try:
        return json.loads(result.stdout), None
    except json.JSONDecodeError:
        return None, f"{command} returned malformed JSON"


def _list_running_castle_names(run: SbxRunner) -> tuple[list[str], str | None]:
    payload, error = _run_json_command(["ls", "--json"], run)
    if error is not None:
        return [], error
    if isinstance(payload, dict):
        payload = payload.get("sandboxes")
    if not isinstance(payload, list):
        return [], "sbx ls --json returned an unexpected shape"
    names = []
    for entry in payload:
        if isinstance(entry, dict) and entry.get("status") == _RUNNING_STATUS:
            name = entry.get("name")
            if isinstance(name, str):
                names.append(name)
    return names, None


def _inspect_castle(
    name: str, run: SbxRunner
) -> tuple[CastleInspection | None, str | None]:
    payload, error = _run_json_command(["inspect", name, "--json"], run)
    if error is not None:
        return None, error
    if not isinstance(payload, dict):
        return None, f"sbx inspect {name} --json returned an unexpected shape"
    vm_state = payload.get("state")
    if not isinstance(vm_state, str):
        vm_state = "unknown"
    uptime = payload.get("uptime_seconds")
    uptime_seconds = float(uptime) if isinstance(uptime, (int, float)) else None
    sessions = payload.get("active_sessions")
    session_count = int(sessions) if isinstance(sessions, int) else None
    return (
        CastleInspection(
            name=name,
            vm_state=vm_state,
            uptime_seconds=uptime_seconds,
            session_count=session_count,
        ),
        None,
    )
