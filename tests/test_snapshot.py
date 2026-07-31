"""Unit tests for the dashboard's snapshot provider seam."""

import dataclasses

import pytest

from sandcastle_dashboard.snapshot import HostRun, Snapshot


def test_snapshot_default_construction_has_no_host_runs():
    snapshot = Snapshot()

    assert snapshot.host_runs == ()


def test_snapshot_is_immutable():
    snapshot = Snapshot()

    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.host_runs = (HostRun(id="host-run-1"),)


def test_snapshot_holds_the_host_runs_it_is_constructed_with():
    host_run = HostRun(id="host-run-1")

    snapshot = Snapshot(host_runs=(host_run,))

    assert snapshot.host_runs == (host_run,)


def test_host_run_equality_is_based_on_its_fields():
    assert HostRun(id="host-run-1") == HostRun(id="host-run-1")
    assert HostRun(id="host-run-1") != HostRun(id="host-run-2")
