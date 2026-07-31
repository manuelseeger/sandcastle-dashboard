"""Unit tests for retaining Host Runs that disappear between polls."""

from __future__ import annotations

from sandcastle_dashboard.host_run_tracker import HostRunTracker
from sandcastle_dashboard.snapshot import HostRun


def test_update_returns_newly_discovered_runs_as_not_ended():
    tracker = HostRunTracker()
    run = HostRun(id="run-1", pid=100, started_at=10.0)

    result = tracker.update((run,))

    assert result == (run,)
    assert result[0].ended is False


def test_update_retains_a_run_that_stops_being_discovered_and_marks_it_ended():
    tracker = HostRunTracker()
    run = HostRun(id="run-1", pid=100, started_at=10.0)
    tracker.update((run,))

    result = tracker.update(())

    assert len(result) == 1
    assert result[0].id == "run-1"
    assert result[0].ended is True


def test_update_keeps_a_still_running_run_marked_not_ended():
    tracker = HostRunTracker()
    run = HostRun(id="run-1", pid=100, started_at=10.0)
    tracker.update((run,))

    result = tracker.update((run,))

    assert result[0].ended is False


def test_update_orders_runs_newest_first():
    tracker = HostRunTracker()
    older = HostRun(id="run-1", pid=100, started_at=10.0)
    newer = HostRun(id="run-2", pid=200, started_at=20.0)

    result = tracker.update((older, newer))

    assert [run.id for run in result] == ["run-2", "run-1"]


def test_update_places_runs_with_unknown_start_time_last():
    tracker = HostRunTracker()
    known_start = HostRun(id="run-1", pid=100, started_at=10.0)
    unknown_start = HostRun(id="run-2", pid=200, started_at=None)

    result = tracker.update((unknown_start, known_start))

    assert [run.id for run in result] == ["run-1", "run-2"]


def test_update_accumulates_newly_started_runs_alongside_existing_ones():
    tracker = HostRunTracker()
    first = HostRun(id="run-1", pid=100, started_at=10.0)
    tracker.update((first,))

    second = HostRun(id="run-2", pid=200, started_at=20.0)
    result = tracker.update((first, second))

    assert {run.id for run in result} == {"run-1", "run-2"}
    assert all(run.ended is False for run in result)
