"""Unit tests for Castle name parsing and Host Run correlation.

Covers the documented `parames-<deployment>-<invocation-or-pid>-<scope>-
<suffix>` naming convention and correlation via explicit Sandcastle
identifiers first, falling back to the PID embedded in the name.
"""

from __future__ import annotations

from sandcastle_dashboard.castle_correlation import correlate_castles, parse_castle_name
from sandcastle_dashboard.sbx import CastleInspection
from sandcastle_dashboard.snapshot import HostRun


def test_parse_castle_name_extracts_issue_scope_and_issue_number():
    parsed = parse_castle_name("parames-prod-4821-issue-9-a1b2c3")

    assert parsed.deployment == "prod"
    assert parsed.invocation_or_pid == "4821"
    assert parsed.scope == "issue"
    assert parsed.scope_id == "9"


def test_parse_castle_name_extracts_planner_scope():
    parsed = parse_castle_name("parames-prod-4821-planner-1-a1b2c3")

    assert parsed.scope == "planner"
    assert parsed.scope_id == "1"


def test_parse_castle_name_extracts_merger_scope_from_merge_keyword():
    parsed = parse_castle_name("parames-prod-4821-merge-7-a1b2c3")

    assert parsed.scope == "merger"
    assert parsed.scope_id == "7"


def test_parse_castle_name_returns_no_scope_for_an_unrecognized_name():
    parsed = parse_castle_name("some-unrelated-name")

    assert parsed.scope is None
    assert parsed.invocation_or_pid is None


def test_correlate_castles_matches_by_pid_when_no_explicit_invocation_id():
    host_run = HostRun(id="run-1", pid=4821)
    inspection = CastleInspection(
        name="parames-prod-4821-issue-9-a1b2c3", vm_state="running"
    )

    castles = correlate_castles([inspection], [host_run])

    assert len(castles) == 1
    castle = castles[0]
    assert castle.host_run_id == "run-1"
    assert castle.scope == "issue"
    assert castle.issue_number == 9
    assert castle.vm_state == "running"


def test_correlate_castles_prefers_explicit_invocation_id_over_pid_lookalike():
    matching_run = HostRun(id="run-explicit", pid=1, invocation_id="9001")
    pid_lookalike_run = HostRun(id="run-pid", pid=9001)
    inspection = CastleInspection(
        name="parames-prod-9001-issue-3-xyz", vm_state="running"
    )

    castles = correlate_castles([inspection], [matching_run, pid_lookalike_run])

    assert len(castles) == 1
    assert castles[0].host_run_id == "run-explicit"


def test_correlate_castles_excludes_a_castle_with_no_matching_host_run():
    host_run = HostRun(id="run-1", pid=1)
    inspection = CastleInspection(
        name="parames-prod-9999-issue-3-xyz", vm_state="running"
    )

    castles = correlate_castles([inspection], [host_run])

    assert castles == ()


def test_correlate_castles_excludes_a_castle_with_an_unrecognized_name():
    host_run = HostRun(id="run-1", pid=1)
    inspection = CastleInspection(name="totally-unrelated", vm_state="running")

    castles = correlate_castles([inspection], [host_run])

    assert castles == ()


def test_correlate_castles_rejects_an_invocation_match_from_the_wrong_deployment():
    """An explicit invocation id could coincidentally collide across
    deployments; when both sides carry a deployment id, it must also agree."""
    wrong_deployment_run = HostRun(
        id="run-wrong-deployment", pid=1, invocation_id="9001", deployment_id="staging"
    )
    inspection = CastleInspection(
        name="parames-prod-9001-issue-3-xyz", vm_state="running"
    )

    castles = correlate_castles([inspection], [wrong_deployment_run])

    assert castles == ()


def test_correlate_castles_carries_uptime_and_session_count_through():
    host_run = HostRun(id="run-1", pid=42)
    inspection = CastleInspection(
        name="parames-prod-42-merge-2-abc",
        vm_state="running",
        uptime_seconds=120.0,
        session_count=1,
    )

    castles = correlate_castles([inspection], [host_run])

    assert castles[0].uptime_seconds == 120.0
    assert castles[0].session_count == 1
    assert castles[0].issue_number is None
