"""Unit tests for the `sbx` JSON adapter.

Covers missing `sbx`, malformed JSON, listing/inspection failures, and
partial results: the acceptance criteria require readable status
information without crashing or discarding otherwise usable results.
"""

from __future__ import annotations

import json
import subprocess

from sandcastle_dashboard.sbx import discover_running_castles


def _completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _runner(responses: dict[tuple[str, ...], subprocess.CompletedProcess]):
    def run(args):
        return responses[tuple(args)]

    return run


def test_discover_running_castles_returns_inspected_running_castles():
    listing = json.dumps(
        [
            {"name": "castle-a", "status": "running"},
            {"name": "castle-b", "status": "stopped"},
        ]
    )
    inspection = json.dumps(
        {"state": "running", "uptime_seconds": 42.5, "active_sessions": 1}
    )
    run = _runner(
        {
            ("ls", "--json"): _completed(stdout=listing),
            ("inspect", "castle-a", "--json"): _completed(stdout=inspection),
        }
    )

    result = discover_running_castles(run)

    assert result.error is None
    assert len(result.castles) == 1
    castle = result.castles[0]
    assert castle.name == "castle-a"
    assert castle.vm_state == "running"
    assert castle.uptime_seconds == 42.5
    assert castle.session_count == 1


def test_discover_running_castles_excludes_stopped_castles_from_inspection():
    listing = json.dumps([{"name": "castle-b", "status": "stopped"}])
    run = _runner({("ls", "--json"): _completed(stdout=listing)})

    result = discover_running_castles(run)

    assert result.castles == ()
    assert result.error is None


def test_discover_running_castles_reports_readable_error_when_sbx_is_missing():
    def run(args):
        raise FileNotFoundError("sbx not found")

    result = discover_running_castles(run)

    assert result.castles == ()
    assert result.error is not None
    assert "sbx" in result.error.lower()


def test_discover_running_castles_reports_readable_error_on_malformed_listing_json():
    run = _runner({("ls", "--json"): _completed(stdout="not json")})

    result = discover_running_castles(run)

    assert result.castles == ()
    assert result.error is not None


def test_discover_running_castles_reports_readable_error_when_listing_command_fails():
    run = _runner(
        {("ls", "--json"): _completed(returncode=1, stderr="daemon unavailable")}
    )

    result = discover_running_castles(run)

    assert result.castles == ()
    assert "daemon unavailable" in result.error


def test_discover_running_castles_keeps_usable_castles_when_one_inspection_fails():
    listing = json.dumps(
        [
            {"name": "castle-a", "status": "running"},
            {"name": "castle-c", "status": "running"},
        ]
    )
    good_inspection = json.dumps({"state": "running"})

    def run(args):
        args = tuple(args)
        if args == ("ls", "--json"):
            return _completed(stdout=listing)
        if args == ("inspect", "castle-a", "--json"):
            return _completed(stdout=good_inspection)
        if args == ("inspect", "castle-c", "--json"):
            return _completed(returncode=1, stderr="inspect timed out")
        raise AssertionError(f"unexpected sbx invocation: {args}")

    result = discover_running_castles(run)

    assert len(result.castles) == 1
    assert result.castles[0].name == "castle-a"
    assert result.error is not None
    assert "castle-c" in result.error


def test_discover_running_castles_reports_error_on_malformed_inspect_json():
    listing = json.dumps([{"name": "castle-a", "status": "running"}])
    run = _runner(
        {
            ("ls", "--json"): _completed(stdout=listing),
            ("inspect", "castle-a", "--json"): _completed(stdout="not json"),
        }
    )

    result = discover_running_castles(run)

    assert result.castles == ()
    assert result.error is not None
