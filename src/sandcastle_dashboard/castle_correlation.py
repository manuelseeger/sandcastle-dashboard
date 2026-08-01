"""Parses Castle names and correlates running Castles with Host Runs.

Castle names use either the legacy convention::

    parames-<deployment>-<invocation-or-pid>-<scope>-<unique suffix>

or the current provider convention::

    <project>-<picker|implement|review>-<issue-id>-<unique suffix>

Legacy names correlate via their invocation identifier or PID. Current names
are correlated through the owning Host Run's descendant ``sbx exec`` process,
which supplies the sandbox name without depending on a project-specific name
prefix.
"""

from __future__ import annotations

from collections.abc import Sequence

from sandcastle_dashboard.sbx import CastleInspection
from sandcastle_dashboard.snapshot import Castle, HostRun

_SCOPE_LABELS = {"planner": "planner", "issue": "issue", "merge": "merger"}
_CURRENT_SCOPE_LABELS = {"picker": "planner", "implement": "issue", "review": "issue"}

# Keep this in sync with the agents configured in .sandcastle/main.mts. Issue
# Castles run the implementer and reviewer sequentially on the same Sonnet model.
_MODEL_BY_SCOPE = {
    "planner": "claude-opus-5",
    "issue": "claude-sonnet-5",
    "merger": "claude-opus-5",
}


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
    for index, token in enumerate(tokens):
        scope = _CURRENT_SCOPE_LABELS.get(token)
        if scope is not None and index + 1 < len(tokens):
            return ParsedCastleName(
                deployment=None,
                invocation_or_pid=None,
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
        host_run_id = _match_host_run(inspection.name, parsed, host_runs)
        if host_run_id is None or parsed.scope is None:
            continue
        castles.append(
            Castle(
                name=inspection.name,
                host_run_id=host_run_id,
                scope=parsed.scope,
                agent_model=_MODEL_BY_SCOPE[parsed.scope],
                issue_number=_as_int(parsed.scope_id)
                if parsed.scope == "issue"
                else None,
                root_number=_as_int(parsed.scope_id)
                if parsed.scope == "merger"
                else None,
                scope_id=parsed.scope_id,
                vm_state=inspection.vm_state,
                uptime_seconds=inspection.uptime_seconds,
                session_count=inspection.session_count,
            )
        )
    return tuple(castles)


def _match_host_run(
    castle_name: str, parsed: ParsedCastleName, host_runs: Sequence[HostRun]
) -> str | None:
    for run in host_runs:
        if castle_name in run.castle_names:
            return run.id
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
