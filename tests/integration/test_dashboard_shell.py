"""Textual pilot integration tests for the installable dashboard shell."""

from __future__ import annotations

import threading
import time

from textual.widgets import RichLog, Static

from sandcastle_dashboard.app import WAITING_MESSAGE, DashboardApp
from sandcastle_dashboard.snapshot import Castle, HostRun, Snapshot


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

    def switch_to(self, snapshot: Snapshot) -> None:
        self._snapshot = snapshot


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
        assert shortcuts.get("left_square_bracket") == "Prev Run"
        assert shortcuts.get("right_square_bracket") == "Next Run"
        assert shortcuts.get("up") == "Up"
        assert shortcuts.get("down") == "Down"
        assert shortcuts.get("left") == "Left"
        assert shortcuts.get("right") == "Right"
        assert shortcuts.get("enter") == "Open Issue"
        assert shortcuts.get("o") == "Open Issue"


async def test_dashboard_app_applies_new_snapshots_automatically_without_blocking():
    provider = SwitchingSnapshotProvider(
        before=Snapshot(),
        after=Snapshot(host_runs=(HostRun(id="host-run-1", pid=123),)),
    )
    app = DashboardApp(snapshot_provider=provider, poll_interval=0.05)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.query_one("#status", Static).content == WAITING_MESSAGE

        provider.switch()
        await pilot.pause(0.4)

        assert "Host Run 1/1" in app.query_one("#status", Static).content


async def test_dashboard_app_selects_the_newest_live_host_run_initially():
    older = HostRun(id="run-older", pid=1, started_at=10.0)
    newer = HostRun(id="run-newer", pid=2, started_at=20.0)
    provider = StaticSnapshotProvider(Snapshot(host_runs=(older, newer)))
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()

        assert app.selected_host_run_id == "run-newer"
        assert "pid 2" in app.query_one("#status", Static).content


async def test_pressing_bracket_keys_switches_the_selected_host_run_immediately():
    older = HostRun(id="run-older", pid=1, started_at=10.0)
    newer = HostRun(id="run-newer", pid=2, started_at=20.0)
    provider = StaticSnapshotProvider(Snapshot(host_runs=(older, newer)))
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.selected_host_run_id == "run-newer"

        await pilot.press("]")
        assert app.selected_host_run_id == "run-older"
        assert "pid 1" in app.query_one("#status", Static).content

        await pilot.press("[")
        assert app.selected_host_run_id == "run-newer"
        assert "pid 2" in app.query_one("#status", Static).content


async def test_dashboard_app_preserves_selection_by_stable_identity_across_snapshots():
    run = HostRun(id="run-1", pid=1, started_at=10.0)
    provider = SwitchingSnapshotProvider(
        before=Snapshot(host_runs=(run,)),
        after=Snapshot(host_runs=(run, HostRun(id="run-2", pid=2, started_at=20.0))),
    )
    app = DashboardApp(snapshot_provider=provider, poll_interval=0.05)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.selected_host_run_id == "run-1"

        provider.switch()
        await pilot.pause(0.4)

        assert app.selected_host_run_id == "run-1"


async def test_dashboard_app_shows_a_disappeared_host_run_with_unknown_outcome():
    run = HostRun(id="run-1", pid=1, started_at=10.0, ended=True)
    provider = StaticSnapshotProvider(Snapshot(host_runs=(run,)))
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()

        assert "unknown" in app.query_one("#status", Static).content


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


async def test_dashboard_app_shows_pid_state_start_time_and_elapsed_time():
    run = HostRun(id="run-1", pid=42, started_at=1_000.0, process_state="sleeping")
    provider = StaticSnapshotProvider(Snapshot(host_runs=(run,)))
    app = DashboardApp(
        snapshot_provider=provider, poll_interval=100, clock=lambda: 1_125.0
    )

    async with app.run_test() as pilot:
        await pilot.pause()

        content = app.query_one("#status", Static).content
        assert "pid 42" in content
        assert "State: sleeping" in content
        assert "Elapsed: 2m05s" in content


async def test_dashboard_app_shows_cpu_and_memory_bars_from_the_snapshot():
    run = HostRun(
        id="run-1",
        pid=42,
        started_at=1_000.0,
        cpu_percent=50.0,
        memory_bytes=512 * 1024 * 1024,
    )
    provider = StaticSnapshotProvider(Snapshot(host_runs=(run,)))
    app = DashboardApp(
        snapshot_provider=provider,
        poll_interval=100,
        cpu_count=1,
        total_memory_bytes=1024 * 1024 * 1024,
    )

    async with app.run_test() as pilot:
        await pilot.pause()

        content = app.query_one("#status", Static).content
        assert "CPU  [██████████░░░░░░░░░░] 50.0%" in content
        assert "MEM  [██████████░░░░░░░░░░] 512.0MiB" in content


async def test_dashboard_app_shows_unavailable_metrics_without_crashing():
    run = HostRun(id="run-1", pid=42, started_at=1_000.0)
    provider = StaticSnapshotProvider(Snapshot(host_runs=(run,)))
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()

        content = app.query_one("#status", Static).content
        assert "measuring" in content
        assert "unknown" in content
        assert "░" * 20 in content


async def test_pressing_q_exits_the_application():
    provider = StaticSnapshotProvider(Snapshot())
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()

    assert app.return_code == 0


def _castle_pane_texts(app: DashboardApp) -> list[str]:
    return [str(header.render()) for header in app.query(".castle-header")]


def _castle_log_lines(app: DashboardApp, pane_id: str) -> list[str]:
    pane = app.query_one(f"#{pane_id}")
    log_widget = pane.query_one(RichLog)
    return [strip.text for strip in log_widget.lines]


def _toast_text(app: DashboardApp) -> str:
    return "\n".join(str(toast.render()) for toast in app.query("Toast"))


async def test_dashboard_app_shows_every_running_castle_for_the_selected_host_run():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    castles = (
        Castle(
            name="parames-prod-42-issue-9-abc",
            host_run_id="run-1",
            scope="issue",
            issue_number=9,
            vm_state="running",
            uptime_seconds=125.0,
            session_count=1,
            branch="sandcastle/issue-9",
        ),
        Castle(
            name="parames-prod-42-merge-3-def",
            host_run_id="run-1",
            scope="merger",
            vm_state="stopped",
            uptime_seconds=None,
            session_count=0,
        ),
    )
    provider = StaticSnapshotProvider(Snapshot(host_runs=(run,), castles=castles))
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()

        panes = app.query(".castle-pane")
        assert len(panes) == 2
        texts = _castle_pane_texts(app)
        assert any(
            "issue" in text
            and "9" in text
            and "running" in text
            and "sandcastle/issue-9" in text
            for text in texts
        )
        assert any(
            "merger" in text and "stopped" in text and "Branch: unknown" in text
            for text in texts
        )


async def test_dashboard_app_shows_an_enriched_github_issue_title():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    castle = Castle(
        name="parames-prod-42-issue-9-abc",
        host_run_id="run-1",
        scope="issue",
        issue_number=9,
        issue_title="Enrich and open focused GitHub issues",
        vm_state="running",
    )
    provider = StaticSnapshotProvider(Snapshot(host_runs=(run,), castles=(castle,)))
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()

        text = _castle_pane_texts(app)[0]
        assert "#9 Enrich and open focused GitHub issues" in text


async def test_dashboard_app_shows_each_castles_agent_model():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    castle = Castle(
        name="parames-prod-42-issue-9-abc",
        host_run_id="run-1",
        scope="issue",
        issue_number=9,
        vm_state="running",
        agent_model="claude-sonnet-5",
    )
    provider = StaticSnapshotProvider(Snapshot(host_runs=(run,), castles=(castle,)))
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()

        text = _castle_pane_texts(app)[0]
        assert "Model: claude-sonnet-5" in text


async def test_dashboard_app_shows_an_issue_castles_inferred_phase():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    castle = Castle(
        name="parames-prod-42-issue-9-abc",
        host_run_id="run-1",
        scope="issue",
        issue_number=9,
        vm_state="running",
        phase="reviewer",
    )
    provider = StaticSnapshotProvider(Snapshot(host_runs=(run,), castles=(castle,)))
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()

        text = _castle_pane_texts(app)[0]
        assert "phase: reviewer" in text


async def test_dashboard_app_shows_provisioning_before_a_role_log_is_active():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    castle = Castle(
        name="parames-prod-42-issue-9-abc",
        host_run_id="run-1",
        scope="issue",
        issue_number=9,
        vm_state="running",
        phase="provisioning",
    )
    provider = StaticSnapshotProvider(Snapshot(host_runs=(run,), castles=(castle,)))
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()

        text = _castle_pane_texts(app)[0]
        assert "phase: provisioning" in text


async def test_dashboard_app_shows_each_castles_last_activity_time():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    castle = Castle(
        name="parames-prod-42-issue-9-abc",
        host_run_id="run-1",
        scope="issue",
        issue_number=9,
        vm_state="running",
        last_activity_at=1_120.0,
    )
    provider = StaticSnapshotProvider(Snapshot(host_runs=(run,), castles=(castle,)))
    app = DashboardApp(
        snapshot_provider=provider, poll_interval=100, clock=lambda: 1_125.0
    )

    async with app.run_test() as pilot:
        await pilot.pause()

        text = _castle_pane_texts(app)[0]
        assert "Last activity: 5s ago" in text


async def test_dashboard_app_shows_the_host_runs_last_activity_time():
    run = HostRun(id="run-1", pid=42, started_at=10.0, last_activity_at=1_100.0)
    provider = StaticSnapshotProvider(Snapshot(host_runs=(run,)))
    app = DashboardApp(
        snapshot_provider=provider, poll_interval=100, clock=lambda: 1_125.0
    )

    async with app.run_test() as pilot:
        await pilot.pause()

        content = app.query_one("#status", Static).content
        assert "Last activity: 25s ago" in content


async def test_dashboard_app_shows_a_bounded_live_log_tail_for_a_castle():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    castle = Castle(
        name="parames-prod-42-issue-9-abc",
        host_run_id="run-1",
        scope="issue",
        issue_number=9,
        vm_state="running",
        phase="implementer",
        log_tail=("Run started 10:00", "exploring the repository", "running tests"),
    )
    provider = StaticSnapshotProvider(Snapshot(host_runs=(run,), castles=(castle,)))
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()

        lines = _castle_log_lines(app, "castle-parames-prod-42-issue-9-abc")
        assert lines == [
            "Run started 10:00",
            "exploring the repository",
            "running tests",
        ]


async def test_dashboard_app_shows_running_castle_count_in_host_run_summary():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    castles = (
        Castle(name="c1", host_run_id="run-1", scope="issue", vm_state="running"),
        Castle(name="c2", host_run_id="run-1", scope="planner", vm_state="running"),
    )
    provider = StaticSnapshotProvider(Snapshot(host_runs=(run,), castles=castles))
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()

        assert "2" in app.query_one("#status", Static).content


async def test_dashboard_app_only_shows_castles_belonging_to_the_selected_host_run():
    selected = HostRun(id="run-selected", pid=1, started_at=20.0)
    other = HostRun(id="run-other", pid=2, started_at=10.0)
    castles = (
        Castle(
            name="c1", host_run_id="run-selected", scope="issue", vm_state="running"
        ),
        Castle(name="c2", host_run_id="run-other", scope="planner", vm_state="running"),
    )
    provider = StaticSnapshotProvider(
        Snapshot(host_runs=(selected, other), castles=castles)
    )
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()

        assert app.selected_host_run_id == "run-selected"
        panes = app.query(".castle-pane")
        assert len(panes) == 1


async def test_dashboard_app_shows_a_message_when_the_selected_host_run_has_no_castles():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    provider = StaticSnapshotProvider(Snapshot(host_runs=(run,)))
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()

        assert len(app.query(".castle-pane")) == 0
        assert (
            "no running castles"
            in app.query_one("#castle-status", Static).content.lower()
        )


async def test_dashboard_app_shows_readable_status_when_castle_discovery_fails():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    provider = StaticSnapshotProvider(
        Snapshot(
            host_runs=(run,),
            castle_discovery_error="sbx is not installed or not on PATH",
        )
    )
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()

        status = app.query_one("#castle-status", Static).content
        assert "sbx is not installed" in status


class SequencedSnapshotProvider:
    """Returns each snapshot in ``snapshots`` in turn, repeating the last."""

    def __init__(self, snapshots: list[Snapshot]) -> None:
        self._snapshots = snapshots
        self.call_count = 0

    def get_snapshot(self) -> Snapshot:
        index = min(self.call_count, len(self._snapshots) - 1)
        self.call_count += 1
        return self._snapshots[index]


async def test_dashboard_app_preserves_castle_panes_when_a_refresh_updates_them():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    initial = Castle(
        name="c1",
        host_run_id="run-1",
        scope="issue",
        vm_state="running",
        phase="implementer",
        log_tail=("starting work",),
    )
    updated = Castle(
        name="c1",
        host_run_id="run-1",
        scope="issue",
        vm_state="running",
        phase="reviewer",
        log_tail=("reviewing changes",),
    )
    provider = SwitchingSnapshotProvider(
        before=Snapshot(host_runs=(run,), castles=(initial,)),
        after=Snapshot(host_runs=(run,), castles=(updated,)),
    )
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()
        pane = app.query_one("#castle-c1")

        provider.switch()
        app._request_refresh()
        await pilot.pause()
        await pilot.pause()

        assert app.query_one("#castle-c1") is pane
        assert "phase: reviewer" in _castle_pane_texts(app)[0]
        assert _castle_log_lines(app, "castle-c1") == ["reviewing changes"]


async def test_dashboard_app_updates_castle_grid_across_refreshes_without_crashing():
    """A changing Castle collection must never leave stale or duplicate panes."""
    run = HostRun(id="run-1", pid=42, started_at=10.0)

    def snapshot_with(count: int) -> Snapshot:
        castles = tuple(
            Castle(name=f"c{i}", host_run_id="run-1", scope="issue", vm_state="running")
            for i in range(count)
        )
        return Snapshot(host_runs=(run,), castles=castles)

    provider = SequencedSnapshotProvider(
        [snapshot_with(3), snapshot_with(1), snapshot_with(0), snapshot_with(2)]
    )
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app.query(".castle-pane")) == 3

        for expected_count in (1, 0, 2):
            app._request_refresh()
            await pilot.pause()
            await pilot.pause()
            assert len(app.query(".castle-pane")) == expected_count


def _focused_castle_name(app: DashboardApp) -> str | None:
    return getattr(app.screen.focused, "castle_name", None)


async def test_castle_grid_arrow_keys_move_spatially_with_incomplete_rows_after_resize():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    castles = tuple(
        Castle(name=f"c{index}", host_run_id="run-1", scope="issue", vm_state="running")
        for index in range(5)
    )
    app = DashboardApp(
        snapshot_provider=StaticSnapshotProvider(
            Snapshot(host_runs=(run,), castles=castles)
        ),
        poll_interval=100,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        assert _focused_castle_name(app) == "c0"
        panes = list(app.query(".castle-pane"))
        assert app.screen.focused.styles.border.top[0] == "heavy"
        assert panes[1].styles.border.top[0] == "round"

        await pilot.resize_terminal(100, 40)
        await pilot.press("down")
        assert _focused_castle_name(app) == "c3"
        await pilot.press("left")
        assert _focused_castle_name(app) == "c3"
        await pilot.press("right")
        assert _focused_castle_name(app) == "c4"
        await pilot.press("up")
        assert _focused_castle_name(app) == "c1"
        await pilot.press("right")
        assert _focused_castle_name(app) == "c2"
        await pilot.press("right")
        assert _focused_castle_name(app) == "c2"
        await pilot.press("down")
        assert _focused_castle_name(app) == "c2"


async def test_castle_grid_arrow_keys_do_not_move_focus_for_a_single_pane():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    castle = Castle(name="c1", host_run_id="run-1", scope="issue", vm_state="running")
    app = DashboardApp(
        snapshot_provider=StaticSnapshotProvider(
            Snapshot(host_runs=(run,), castles=(castle,))
        ),
        poll_interval=100,
    )

    async with app.run_test() as pilot:
        await pilot.pause()

        for key in ("up", "down", "left", "right"):
            await pilot.press(key)
            assert _focused_castle_name(app) == "c1"


async def test_castle_grid_refresh_preserves_identity_then_falls_back_and_resets_for_run():
    first_run = HostRun(id="run-1", pid=1, started_at=10.0)
    second_run = HostRun(id="run-2", pid=2, started_at=20.0)
    provider = SwitchingSnapshotProvider(
        before=Snapshot(
            host_runs=(first_run,),
            castles=tuple(
                Castle(
                    name=name,
                    host_run_id="run-1",
                    scope="issue",
                    vm_state="running",
                )
                for name in ("a", "b", "c")
            ),
        ),
        after=Snapshot(
            host_runs=(first_run, second_run),
            castles=(
                Castle(
                    name="a", host_run_id="run-1", scope="issue", vm_state="running"
                ),
                Castle(
                    name="new",
                    host_run_id="run-1",
                    scope="issue",
                    vm_state="running",
                ),
                Castle(
                    name="b",
                    host_run_id="run-1",
                    scope="issue",
                    vm_state="running",
                    phase="reviewer",
                ),
                Castle(
                    name="run-2-castle",
                    host_run_id="run-2",
                    scope="planner",
                    vm_state="running",
                ),
            ),
        ),
    )
    app = DashboardApp(snapshot_provider=provider, poll_interval=100)

    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("right")
        assert _focused_castle_name(app) == "b"

        provider.switch()
        app._request_refresh()
        await pilot.pause()
        await pilot.pause()
        assert _focused_castle_name(app) == "b"
        assert any(
            "b" in text and "phase: reviewer" in text
            for text in _castle_pane_texts(app)
        )

        provider.switch_to(
            Snapshot(
                host_runs=(first_run, second_run),
                castles=(
                    Castle(
                        name="a",
                        host_run_id="run-1",
                        scope="issue",
                        vm_state="running",
                    ),
                    Castle(
                        name="new",
                        host_run_id="run-1",
                        scope="issue",
                        vm_state="running",
                    ),
                    Castle(
                        name="run-2-castle",
                        host_run_id="run-2",
                        scope="planner",
                        vm_state="running",
                    ),
                ),
            )
        )
        app._request_refresh()
        await pilot.pause()
        await pilot.pause()
        assert _focused_castle_name(app) == "new"

        await pilot.press("]")
        assert app.selected_host_run_id == "run-2"
        assert _focused_castle_name(app) == "run-2-castle"


async def test_pressing_enter_and_o_open_the_focused_castles_github_issue_url():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    castle = Castle(
        name="issue-castle",
        host_run_id="run-1",
        scope="issue",
        issue_number=9,
        issue_url="https://github.com/example/project/issues/9",
        vm_state="running",
    )
    opened_urls: list[str] = []
    app = DashboardApp(
        snapshot_provider=StaticSnapshotProvider(
            Snapshot(host_runs=(run,), castles=(castle,))
        ),
        poll_interval=100,
        url_opener=lambda url: opened_urls.append(url) or True,
    )

    async with app.run_test() as pilot:
        await pilot.pause()

        await pilot.press("enter")
        await pilot.press("o")

        assert opened_urls == [
            "https://github.com/example/project/issues/9",
            "https://github.com/example/project/issues/9",
        ]


async def test_open_issue_when_url_opener_fails_shows_readable_notification():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    castle = Castle(
        name="issue-castle",
        host_run_id="run-1",
        scope="issue",
        issue_number=9,
        issue_url="https://github.com/example/project/issues/9",
        vm_state="running",
    )

    def broken_opener(_url):
        raise OSError("browser unavailable")

    app = DashboardApp(
        snapshot_provider=StaticSnapshotProvider(
            Snapshot(host_runs=(run,), castles=(castle,))
        ),
        poll_interval=100,
        url_opener=broken_opener,
    )

    async with app.run_test(notifications=True) as pilot:
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert "Could not open" in _toast_text(app)
        assert app.is_running


async def test_open_issue_for_a_castle_without_an_issue_shows_readable_notification():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    castle = Castle(
        name="planner-castle",
        host_run_id="run-1",
        scope="planner",
        vm_state="running",
    )
    app = DashboardApp(
        snapshot_provider=StaticSnapshotProvider(
            Snapshot(host_runs=(run,), castles=(castle,))
        ),
        poll_interval=100,
    )

    async with app.run_test(notifications=True) as pilot:
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert "no GitHub issue" in _toast_text(app)


async def test_open_issue_without_an_enriched_url_shows_readable_notification():
    run = HostRun(id="run-1", pid=42, started_at=10.0)
    castle = Castle(
        name="issue-castle",
        host_run_id="run-1",
        scope="issue",
        issue_number=9,
        vm_state="running",
    )
    app = DashboardApp(
        snapshot_provider=StaticSnapshotProvider(
            Snapshot(host_runs=(run,), castles=(castle,))
        ),
        poll_interval=100,
    )

    async with app.run_test(notifications=True) as pilot:
        await pilot.pause()

        await pilot.press("o")
        await pilot.pause()

        assert "URL is unavailable" in _toast_text(app)
