"""Textual pilot integration tests for the installable dashboard shell."""

from __future__ import annotations

import threading
import time

from textual.widgets import Static

from sandcastle_dashboard.app import WAITING_MESSAGE, DashboardApp
from sandcastle_dashboard.snapshot import HostRun, Snapshot


class StaticSnapshotProvider:
    """Always returns the same snapshot; counts how often it is asked."""

    def __init__(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        self.call_count = 0

    def get_snapshot(self) -> Snapshot:
        self.call_count += 1
        return self.snapshot


class SwitchingSnapshotProvider:
    """Returns one snapshot until switched, then returns another."""

    def __init__(self, before: Snapshot, after: Snapshot) -> None:
        self._snapshot = before
        self._after = after
        self.call_count = 0

    def get_snapshot(self) -> Snapshot:
        self.call_count += 1
        return self._snapshot

    def switch(self) -> None:
        self._snapshot = self._after


class ConcurrencyTrackingSnapshotProvider:
    """Blocks on every call and records the maximum concurrent call count."""

    def __init__(self, snapshot: Snapshot, block_seconds: float) -> None:
        self._snapshot = snapshot
        self._block_seconds = block_seconds
        self._lock = threading.Lock()
        self._current = 0
        self.call_count = 0
        self.max_concurrent = 0

    def get_snapshot(self) -> Snapshot:
        with self._lock:
            self.call_count += 1
            self._current += 1
            self.max_concurrent = max(self.max_concurrent, self._current)
        time.sleep(self._block_seconds)
        with self._lock:
            self._current -= 1
        return self._snapshot


def _footer_shortcuts(app: DashboardApp) -> dict[str, str]:
    return {key.key: key.description for key in app.query("FooterKey")}


async def test_dashboard_app_with_empty_snapshot_shows_waiting_state_and_shortcuts():
    provider = StaticSnapshotProvider(Snapshot())
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()

        status = app.query_one("#status", Static)
        assert status.content == WAITING_MESSAGE

        shortcuts = _footer_shortcuts(app)
        assert shortcuts.get("r") == "Refresh"
        assert shortcuts.get("q") == "Quit"


async def test_dashboard_app_applies_new_snapshots_automatically_without_blocking():
    provider = SwitchingSnapshotProvider(
        before=Snapshot(),
        after=Snapshot(host_runs=(HostRun(id="host-run-1"),)),
    )
    app = DashboardApp(snapshot_provider=provider, poll_interval=0.05)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#status", Static).content == WAITING_MESSAGE

        provider.switch()
        await pilot.pause(0.4)

        assert "1 Host Run" in app.query_one("#status", Static).content


async def test_dashboard_app_never_overlaps_slow_automatic_refreshes():
    provider = ConcurrencyTrackingSnapshotProvider(Snapshot(), block_seconds=0.2)
    app = DashboardApp(snapshot_provider=provider, poll_interval=0.02)

    async with app.run_test() as pilot:
        await pilot.pause(0.5)

    assert provider.call_count >= 1
    assert provider.max_concurrent == 1


async def test_pressing_r_requests_an_immediate_refresh():
    provider = StaticSnapshotProvider(Snapshot())
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()
        calls_before_refresh = provider.call_count

        await pilot.press("r")
        await pilot.pause(0.2)

        assert provider.call_count > calls_before_refresh


async def test_pressing_q_exits_the_application():
    provider = StaticSnapshotProvider(Snapshot())
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()

    assert app.return_code == 0
