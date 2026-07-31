"""The Sandcastle dashboard's Textual application shell."""

from __future__ import annotations

import asyncio
import math
import re
import time
import webbrowser
from collections.abc import Callable, Sequence
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Grid, Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, RichLog, Static

from sandcastle_dashboard import system_resources
from sandcastle_dashboard.bars import render_bar
from sandcastle_dashboard.formatting import (
    format_bytes,
    format_duration,
    format_timestamp,
)
from sandcastle_dashboard.snapshot import Castle, HostRun, Snapshot, SnapshotProvider

WAITING_MESSAGE = (
    "No Host Run detected.\nWaiting for a Sandcastle orchestration run to start..."
)
NO_CASTLES_MESSAGE = "No running Castles for this Host Run."

_SLUG_PATTERN = re.compile(r"[^a-zA-Z0-9_-]+")


def _slug(text: str) -> str:
    return _SLUG_PATTERN.sub("-", text).strip("-") or "castle"


def _format_uptime(uptime_seconds: float | None) -> str:
    if uptime_seconds is None:
        return "uptime unknown"
    total_seconds = int(uptime_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"uptime {hours}h{minutes}m"
    if minutes:
        return f"uptime {minutes}m{seconds}s"
    return f"uptime {seconds}s"


def _format_scope(castle: Castle) -> str:
    if castle.scope == "issue" and castle.issue_number is not None:
        label = f"issue #{castle.issue_number}"
        return f"{label} {castle.issue_title}" if castle.issue_title else label
    return castle.scope


def _format_branch(castle: Castle) -> str:
    return (
        f"Branch: {castle.branch}" if castle.branch is not None else "Branch: unknown"
    )


def _castles_for_host_run(
    castles: Sequence[Castle], host_run_id: str | None
) -> list[Castle]:
    if host_run_id is None:
        return []
    return [castle for castle in castles if castle.host_run_id == host_run_id]


def _grid_dimensions(castle_count: int) -> tuple[int, int]:
    """Return the adaptive grid dimensions for a non-empty Castle collection."""
    columns = math.ceil(math.sqrt(castle_count))
    return columns, math.ceil(castle_count / columns)


class CastlePane(Vertical):
    """A focusable Castle grid cell identified by its stable Castle name."""

    can_focus = True
    can_focus_children = False


class CastleLog(RichLog):
    """A display-only log that does not intercept grid navigation keys."""

    can_focus = False


CPU_UNKNOWN_LABEL = "measuring…"
MEMORY_UNKNOWN_LABEL = "unknown"
BAR_WIDTH = 20


def _ordered_host_runs(host_runs: Sequence[HostRun]) -> list[HostRun]:
    """Order Host Runs newest-first; runs with an unknown start time sort last."""
    return sorted(
        host_runs,
        key=lambda run: run.started_at if run.started_at is not None else float("-inf"),
        reverse=True,
    )


def _newest_live_id(ordered: Sequence[HostRun]) -> str | None:
    """The default selection: the newest live run, or the newest run overall."""
    for run in ordered:
        if not run.ended:
            return run.id
    return ordered[0].id if ordered else None


class DashboardApp(App[None]):
    """Polls an injected ``SnapshotProvider`` and renders dashboard state.

    Selects the newest live Host Run initially and lets the operator switch
    with ``[``/``]``. Every running Castle correlated to the selected Host
    Run is shown in an adaptive equal-sized grid below the summary line.
    """

    CSS = """
    #content {
        height: 1fr;
    }
    #status {
        height: auto;
    }
    #castle-status {
        height: auto;
        color: $warning;
    }
    #castle-grid {
        height: 1fr;
    }
    .castle-pane {
        border: round $primary;
        height: 1fr;
        padding: 0 1;
    }
    .castle-pane:focus {
        background: $accent 20%;
        border: heavy $accent;
    }
    .castle-header {
        height: auto;
    }
    .castle-log {
        height: 1fr;
        border: none;
        padding: 0;
        scrollbar-size: 0 0;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
        Binding("[", "previous_host_run", "Prev Run"),
        Binding("]", "next_host_run", "Next Run"),
        Binding("up", "focus_castle_up", "Up"),
        Binding("down", "focus_castle_down", "Down"),
        Binding("left", "focus_castle_left", "Left"),
        Binding("right", "focus_castle_right", "Right"),
        Binding("enter", "open_issue", "Open Issue"),
        Binding("o", "open_issue_alternate", "Open Issue"),
    ]

    snapshot: reactive[Snapshot] = reactive(Snapshot(), always_update=True)
    selected_host_run_id: reactive[str | None] = reactive(None)

    def __init__(
        self,
        snapshot_provider: SnapshotProvider,
        poll_interval: float = 2.0,
        clock: Callable[[], float] = time.time,
        cpu_count: int | None = None,
        total_memory_bytes: int | None = None,
        url_opener: Callable[[str], bool] = webbrowser.open,
    ) -> None:
        super().__init__()
        self._snapshot_provider = snapshot_provider
        self._poll_interval = poll_interval
        self._refresh_in_progress = False
        self._clock = clock
        self._cpu_count = (
            cpu_count if cpu_count is not None else system_resources.cpu_count()
        )
        self._total_memory_bytes = (
            total_memory_bytes
            if total_memory_bytes is not None
            else system_resources.total_memory_bytes()
        )
        self._grid_host_run_id: str | None = None
        self._url_opener = url_opener

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="content"):
            yield Static(WAITING_MESSAGE, id="status", markup=False)
            yield Static("", id="castle-status")
            yield Grid(id="castle-grid")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(self._poll_interval, self._request_refresh)
        self._request_refresh()

    def action_refresh(self) -> None:
        self._request_refresh()

    def _request_refresh(self) -> None:
        self.run_worker(self._poll(), exclusive=False, group="snapshot-poll")

    async def _poll(self) -> None:
        if self._refresh_in_progress:
            return
        self._refresh_in_progress = True
        try:
            self.snapshot = await asyncio.to_thread(
                self._snapshot_provider.get_snapshot
            )
        finally:
            self._refresh_in_progress = False

    async def action_previous_host_run(self) -> None:
        await self._cycle_host_run(-1)

    async def action_next_host_run(self) -> None:
        await self._cycle_host_run(1)

    def action_focus_castle_up(self) -> None:
        self._move_castle_focus("up")

    def action_focus_castle_down(self) -> None:
        self._move_castle_focus("down")

    def action_focus_castle_left(self) -> None:
        self._move_castle_focus("left")

    def action_focus_castle_right(self) -> None:
        self._move_castle_focus("right")

    def action_open_issue_alternate(self) -> None:
        self.action_open_issue()

    def action_open_issue(self) -> None:
        focused_name = getattr(self.screen.focused, "castle_name", None)
        castle = next(
            (
                castle
                for castle in self.snapshot.castles
                if castle.host_run_id == self.selected_host_run_id
                and castle.name == focused_name
            ),
            None,
        )
        if castle is None or castle.issue_number is None:
            self.notify(
                "The focused Castle has no GitHub issue.",
                severity="warning",
                markup=False,
            )
            return
        if castle.issue_url is None:
            self.notify(
                f"GitHub issue #{castle.issue_number} URL is unavailable.",
                severity="warning",
                markup=False,
            )
            return
        try:
            opened = self._url_opener(castle.issue_url)
        except OSError, webbrowser.Error:
            opened = False
        if not opened:
            self.notify(
                f"Could not open GitHub issue #{castle.issue_number}.",
                severity="error",
                markup=False,
            )

    def _move_castle_focus(self, direction: str) -> None:
        panes = list(self.query("#castle-grid CastlePane"))
        if not panes:
            return
        focused = self.screen.focused
        if not isinstance(focused, CastlePane) or focused not in panes:
            panes[0].focus()
            return
        index = panes.index(focused)
        columns, _ = _grid_dimensions(len(panes))
        target_index = index
        if direction == "left" and index % columns:
            target_index = index - 1
        elif direction == "right" and index % columns < columns - 1:
            target_index = index + 1
        elif direction == "up" and index >= columns:
            target_index = index - columns
        elif direction == "down" and index + columns < len(panes):
            target_index = index + columns
        if target_index < len(panes):
            panes[target_index].focus()

    async def _cycle_host_run(self, step: int) -> None:
        ordered = _ordered_host_runs(self.snapshot.host_runs)
        if not ordered:
            return
        ids = [run.id for run in ordered]
        try:
            index = ids.index(self.selected_host_run_id)
        except ValueError:
            index = 0
        self.selected_host_run_id = ids[(index + step) % len(ids)]
        await self._render_status()

    async def watch_snapshot(self, snapshot: Snapshot) -> None:
        if not self.is_running:
            return
        ordered = _ordered_host_runs(snapshot.host_runs)
        known_ids = {run.id for run in ordered}
        if self.selected_host_run_id not in known_ids:
            self.selected_host_run_id = _newest_live_id(ordered)
        await self._render_status()

    async def _render_status(self) -> None:
        status = self.query_one("#status", Static)
        castle_status = self.query_one("#castle-status", Static)
        ordered = _ordered_host_runs(self.snapshot.host_runs)
        if not ordered:
            self._update_static(status, WAITING_MESSAGE)
            self._update_static(castle_status, "")
            await self._render_castle_grid([])
            return
        ids = [run.id for run in ordered]
        try:
            index = ids.index(self.selected_host_run_id)
        except ValueError:
            index = 0
        selected = ordered[index]
        outcome = "unknown" if selected.ended else "live"
        repo_name = (
            selected.repository.name if selected.repository else "unknown repository"
        )
        castles = _castles_for_host_run(self.snapshot.castles, selected.id)
        castle_count = len(castles)
        castle_noun = "castle" if castle_count == 1 else "castles"
        self._update_static(
            status,
            f"Host Run {index + 1}/{len(ordered)} — pid {selected.pid} "
            f"• {repo_name} • {outcome} • {castle_count} running {castle_noun}\n"
            f"{self._render_operational_summary(selected)}\n"
            f"{self._render_resource_bars(selected)}",
        )
        self._update_static(castle_status, self.snapshot.castle_discovery_error or "")
        await self._render_castle_grid(castles)

    @staticmethod
    def _update_static(widget: Static, content: str) -> None:
        """Update a text widget only when its displayed value changed."""
        if widget.content != content:
            widget.update(content)

    def _render_operational_summary(self, host_run: HostRun) -> str:
        started_label = (
            format_timestamp(host_run.started_at)
            if host_run.started_at is not None
            else "unknown"
        )
        elapsed_label = (
            format_duration(self._clock() - host_run.started_at)
            if host_run.started_at is not None
            else "unknown"
        )
        return (
            f"State: {host_run.process_state}   "
            f"Started: {started_label}   "
            f"Elapsed: {elapsed_label}   "
            f"Last activity: {self._format_relative_time(host_run.last_activity_at)}"
        )

    def _format_relative_time(self, timestamp: float | None) -> str:
        if timestamp is None:
            return "no activity yet"
        return f"{format_duration(max(0.0, self._clock() - timestamp))} ago"

    def _render_resource_bars(self, host_run: HostRun) -> str:
        cpu_capacity = self._cpu_count * 100
        cpu_fraction = (
            host_run.cpu_percent / cpu_capacity
            if host_run.cpu_percent is not None
            else None
        )
        cpu_label = (
            f"{host_run.cpu_percent:.1f}%"
            if host_run.cpu_percent is not None
            else CPU_UNKNOWN_LABEL
        )
        memory_fraction = (
            host_run.memory_bytes / self._total_memory_bytes
            if host_run.memory_bytes is not None and self._total_memory_bytes
            else None
        )
        memory_label = (
            format_bytes(host_run.memory_bytes)
            if host_run.memory_bytes is not None
            else MEMORY_UNKNOWN_LABEL
        )
        return (
            f"CPU  [{render_bar(cpu_fraction, width=BAR_WIDTH)}] {cpu_label}\n"
            f"MEM  [{render_bar(memory_fraction, width=BAR_WIDTH)}] {memory_label}"
        )

    async def _render_castle_grid(self, castles: Sequence[Castle]) -> None:
        """Apply Castle changes in place so polling does not redraw the whole grid."""
        grid = self.query_one("#castle-grid", Grid)
        focused = self.screen.focused
        previous_panes = list(grid.query(CastlePane))
        previous_index = (
            previous_panes.index(focused)
            if isinstance(focused, CastlePane)
            and focused in previous_panes
            and self._grid_host_run_id == self.selected_host_run_id
            else None
        )
        previous_name = focused.castle_name if previous_index is not None else None
        existing_panes = {pane.castle_name: pane for pane in previous_panes}
        desired_names = {castle.name for castle in castles}

        panes_to_remove = [
            pane for name, pane in existing_panes.items() if name not in desired_names
        ]
        if panes_to_remove:
            await grid.remove_children(panes_to_remove)

        new_panes: list[CastlePane] = []
        panes: list[tuple[CastlePane, Castle]] = []
        for castle in castles:
            pane = existing_panes.get(castle.name)
            if pane is None:
                pane = self._build_castle_pane(castle)
                new_panes.append(pane)
            panes.append((pane, castle))
        if new_panes:
            await grid.mount_all(new_panes)

        self._grid_host_run_id = self.selected_host_run_id
        if not castles:
            if isinstance(focused, CastlePane):
                self.set_focus(None)
            self._set_grid_dimensions(grid, columns=1, rows=1)
            castle_status = self.query_one("#castle-status", Static)
            if not castle_status.content:
                self._update_static(castle_status, NO_CASTLES_MESSAGE)
            return

        columns, rows = _grid_dimensions(len(castles))
        self._set_grid_dimensions(grid, columns=columns, rows=rows)
        self._order_panes(grid, [pane for pane, _ in panes])
        for pane, castle in panes:
            self._update_castle_pane(pane, castle)

        if previous_name is not None and previous_name in desired_names:
            return
        focus_index = min(previous_index, len(panes) - 1) if previous_index else 0
        panes[focus_index][0].focus()

    @staticmethod
    def _set_grid_dimensions(grid: Grid, columns: int, rows: int) -> None:
        if grid.styles.grid_size_columns != columns:
            grid.styles.grid_size_columns = columns
        if grid.styles.grid_size_rows != rows:
            grid.styles.grid_size_rows = rows

    @staticmethod
    def _order_panes(grid: Grid, panes: Sequence[CastlePane]) -> None:
        for index, pane in enumerate(panes):
            children = list(grid.children)
            if children[index] is not pane:
                grid.move_child(pane, before=children[index])

    def _update_castle_pane(self, pane: CastlePane, castle: Castle) -> None:
        header = pane.query_one(".castle-header", Static)
        self._update_static(header, self._castle_header_text(castle))
        if pane.log_tail != castle.log_tail:
            log_widget = pane.query_one(CastleLog)
            log_widget.clear()
            for line in castle.log_tail:
                log_widget.write(line)
            pane.log_tail = castle.log_tail

    def _build_castle_pane(self, castle: Castle) -> CastlePane:
        pane = CastlePane(
            Static(
                self._castle_header_text(castle),
                classes="castle-header",
                markup=False,
            ),
            CastleLog(classes="castle-log", markup=False, highlight=False, wrap=False),
            classes="castle-pane",
            id=f"castle-{_slug(castle.name)}",
        )
        pane.castle_name = castle.name
        pane.log_tail: tuple[str, ...] | None = None
        return pane

    def _castle_header_text(self, castle: Castle) -> str:
        sessions = (
            "unknown" if castle.session_count is None else str(castle.session_count)
        )
        return (
            f"{castle.name}\n"
            f"{_format_scope(castle)} • phase: {castle.phase} • {castle.vm_state}\n"
            f"{_format_uptime(castle.uptime_seconds)} • {sessions} session(s)\n"
            f"{_format_branch(castle)}\n"
            f"Last activity: {self._format_relative_time(castle.last_activity_at)}"
        )
