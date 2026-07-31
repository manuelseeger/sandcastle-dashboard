"""Unit tests for the sandcastle-dashboard console entry point wiring."""

from click.testing import CliRunner

from sandcastle_dashboard import cli
from sandcastle_dashboard.live_snapshot_provider import LiveHostRunSnapshotProvider
from sandcastle_dashboard.snapshot import Snapshot


def test_main_runs_the_dashboard_app_with_a_live_host_run_snapshot_provider(
    monkeypatch,
):
    captured = {}

    class FakeDashboardApp:
        def __init__(self, snapshot_provider):
            captured["snapshot_provider"] = snapshot_provider

        def run(self):
            captured["ran"] = True

    monkeypatch.setattr(cli, "DashboardApp", FakeDashboardApp)
    monkeypatch.setattr(
        LiveHostRunSnapshotProvider, "get_snapshot", lambda _provider: Snapshot()
    )

    result = CliRunner().invoke(cli.main)

    assert result.exit_code == 0
    assert captured["ran"] is True
    provider = captured["snapshot_provider"]
    assert isinstance(provider, LiveHostRunSnapshotProvider)
    assert isinstance(provider.get_snapshot(), Snapshot)
