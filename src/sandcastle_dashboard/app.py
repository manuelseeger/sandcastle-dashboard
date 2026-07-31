"""The Sandcastle dashboard's Textual application shell."""

from __future__ import annotations

import asyncio
import math
import re
import time
from collections.abc import Callable, Sequence
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Grid
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static

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
        return f"issue #{castle.issue_number}"
    return castle.scope


def _castle_pane_text(castle: Castle) -> str:
    sessions = "unknown" if castle.session_count is None else str(castle.session_count)
    return (
        f"{castle.name}\n"
        f"{_format_scope(castle)} • {castle.vm_state}\n"
        f"{_format_uptime(castle.uptime_seconds)} • {sessions} session(s)"
    )


def _castles_for_host_run(
    castles: Sequence[Castle], host_run_id: str | None
) -> list[Castle]:
    if host_run_id is None:
        return []
    return [castle for castle in castles if castle.host_run_id == host_run_id]


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
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
        Binding("[", "previous_host_run", "Prev Run"),
        Binding("]", "next_host_run", "Next Run"),
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
            status.update(WAITING_MESSAGE)
            castle_status.update("")
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
        status.update(
            f"Host Run {index + 1}/{len(ordered)} — pid {selected.pid} "
            f"• {repo_name} • {outcome} • {castle_count} running {castle_noun}\n"
            f"{self._render_operational_summary(selected)}\n"
            f"{self._render_resource_bars(selected)}"
        )
        castle_status.update(self.snapshot.castle_discovery_error or "")
        await self._render_castle_grid(castles)

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
            f"Elapsed: {elapsed_label}"
        )

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
        grid = self.query_one("#castle-grid", Grid)
        await grid.remove_children()
        if not castles:
            grid.styles.grid_size_columns = 1
            grid.styles.grid_size_rows = 1
            castle_status = self.query_one("#castle-status", Static)
            if not castle_status.content:
                castle_status.update(NO_CASTLES_MESSAGE)
            return
        columns = math.ceil(math.sqrt(len(castles)))
        rows = math.ceil(len(castles) / columns)
        grid.styles.grid_size_columns = columns
        grid.styles.grid_size_rows = rows
        await grid.mount_all(
            Static(
                _castle_pane_text(castle),
                classes="castle-pane",
                id=f"castle-{_slug(castle.name)}",
            )
            for castle in castles
        )
