"""Parses Castle names and correlates running Castles with Host Runs.

Castle names follow the documented convention::

    parames-<deployment>-<invocation-or-pid>-<scope>-<unique suffix>

The ``<invocation-or-pid>`` segment holds an explicit
``SANDCASTLE_INVOCATION_ID`` when the Host Run set one, or the
orchestrator's PID otherwise. Correlation matches an explicit Host Run
invocation identifier first, then falls back to comparing the segment
against a Host Run's PID.
"""

from __future__ import annotations

from collections.abc import Sequence

from sandcastle_dashboard.sbx import CastleInspection
from sandcastle_dashboard.snapshot import Castle, HostRun

_SCOPE_LABELS = {"planner": "planner", "issue": "issue", "merge": "merger"}


class ParsedCastleName:
    """The correlation-relevant segments of a Castle name, if recognized."""

    __slots__ = ("deployment", "invocation_or_pid", "scope", "scope_id")

    def __init__(
        self,
        deployment: str | None,
        invocation_or_pid: str | None,
        scope: str | None,
        scope_id: str | None,
    ) -> None:
        self.deployment = deployment
        self.invocation_or_pid = invocation_or_pid
        self.scope = scope
        self.scope_id = scope_id


def parse_castle_name(name: str) -> ParsedCastleName:
    """Parse a Castle name against the documented naming convention.

    Returns a ``ParsedCastleName`` with every field ``None`` when ``name``
    does not contain a recognized scope keyword.
    """
    tokens = name.split("-")
    for index, token in enumerate(tokens):
        scope = _SCOPE_LABELS.get(token)
        if scope is None or index < 1 or index + 1 >= len(tokens):
            continue
        deployment = tokens[1] if index >= 2 else None
        return ParsedCastleName(
            deployment=deployment,
            invocation_or_pid=tokens[index - 1],
            scope=scope,
            scope_id=tokens[index + 1],
        )
    return ParsedCastleName(None, None, None, None)


def correlate_castles(
    inspections: Sequence[CastleInspection], host_runs: Sequence[HostRun]
) -> tuple[Castle, ...]:
    """Correlate running Castle inspections to the Host Runs that own them.

    A Castle whose name is unrecognized or whose invocation/PID segment
    matches no known Host Run is excluded rather than guessed at.
    """
    castles = []
    for inspection in inspections:
        parsed = parse_castle_name(inspection.name)
        host_run_id = _match_host_run(parsed, host_runs)
        if host_run_id is None or parsed.scope is None:
            continue
        castles.append(
            Castle(
                name=inspection.name,
                host_run_id=host_run_id,
                scope=parsed.scope,
                issue_number=_as_int(parsed.scope_id)
                if parsed.scope == "issue"
                else None,
                vm_state=inspection.vm_state,
                uptime_seconds=inspection.uptime_seconds,
                session_count=inspection.session_count,
            )
        )
    return tuple(castles)


def _match_host_run(
    parsed: ParsedCastleName, host_runs: Sequence[HostRun]
) -> str | None:
    if parsed.invocation_or_pid is None:
        return None
    for run in host_runs:
        if run.invocation_id is None or run.invocation_id != parsed.invocation_or_pid:
            continue
        if (
            run.deployment_id is not None
            and parsed.deployment is not None
            and run.deployment_id != parsed.deployment
        ):
            continue
        return run.id
    segment_pid = _as_int(parsed.invocation_or_pid)
    if segment_pid is None:
        return None
    for run in host_runs:
        if run.invocation_id is None and run.pid == segment_pid:
            return run.id
    return None


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None
