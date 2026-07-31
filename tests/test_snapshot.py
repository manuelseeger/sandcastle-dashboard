"""Unit tests for the dashboard's snapshot provider seam."""

import dataclasses

import pytest

from sandcastle_dashboard.snapshot import HostRun, Repository, Snapshot


def test_snapshot_default_construction_has_no_host_runs():
    snapshot = Snapshot()

    assert snapshot.host_runs == ()


def test_snapshot_is_immutable():
    snapshot = Snapshot()

    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.host_runs = (HostRun(id="host-run-1", pid=123),)


def test_snapshot_holds_the_host_runs_it_is_constructed_with():
    host_run = HostRun(id="host-run-1", pid=123)

    snapshot = Snapshot(host_runs=(host_run,))

    assert snapshot.host_runs == (host_run,)


def test_host_run_equality_is_based_on_its_fields():
    assert HostRun(id="host-run-1", pid=123) == HostRun(id="host-run-1", pid=123)
    assert HostRun(id="host-run-1", pid=123) != HostRun(id="host-run-2", pid=123)


def test_host_run_defaults_to_no_repository_and_not_ended():
    host_run = HostRun(id="host-run-1", pid=123)

    assert host_run.repository is None
    assert host_run.ended is False
    assert host_run.process_group_pids == ()


def test_host_run_defaults_to_unknown_cpu_and_memory():
    host_run = HostRun(id="host-run-1", pid=123)

    assert host_run.cpu_percent is None
    assert host_run.memory_bytes is None


def test_host_run_holds_the_cpu_and_memory_it_is_constructed_with():
    host_run = HostRun(id="host-run-1", pid=123, cpu_percent=12.5, memory_bytes=2048)

    assert host_run.cpu_percent == 12.5
    assert host_run.memory_bytes == 2048


def test_host_run_is_immutable():
    host_run = HostRun(id="host-run-1", pid=123)

    with pytest.raises(dataclasses.FrozenInstanceError):
        host_run.ended = True


def test_repository_equality_is_based_on_its_fields():
    assert Repository(path="/repo", name="repo") == Repository(
        path="/repo", name="repo"
    )
    assert Repository(path="/repo", name="repo") != Repository(
        path="/other", name="other"
    )
