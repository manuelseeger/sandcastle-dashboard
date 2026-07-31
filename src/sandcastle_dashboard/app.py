"""The Sandcastle dashboard's Textual application shell."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Sequence
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static

from sandcastle_dashboard import system_resources
from sandcastle_dashboard.bars import render_bar
from sandcastle_dashboard.formatting import (
    format_bytes,
    format_duration,
    format_timestamp,
)
from sandcastle_dashboard.snapshot import HostRun, Snapshot, SnapshotProvider

WAITING_MESSAGE = (
    "No Host Run detected.\nWaiting for a Sandcastle orchestration run to start..."
)

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
    with ``[``/``]``. A later issue adds the Castle grid on top of this
    shell.
    """

    CSS = """
    #content {
        align: center middle;
        height: 1fr;
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

    def action_previous_host_run(self) -> None:
        self._cycle_host_run(-1)

    def action_next_host_run(self) -> None:
        self._cycle_host_run(1)

    def _cycle_host_run(self, step: int) -> None:
        ordered = _ordered_host_runs(self.snapshot.host_runs)
        if not ordered:
            return
        ids = [run.id for run in ordered]
        try:
            index = ids.index(self.selected_host_run_id)
        except ValueError:
            index = 0
        self.selected_host_run_id = ids[(index + step) % len(ids)]
        self._render_status()

    def watch_snapshot(self, snapshot: Snapshot) -> None:
        ordered = _ordered_host_runs(snapshot.host_runs)
        known_ids = {run.id for run in ordered}
        if self.selected_host_run_id not in known_ids:
            self.selected_host_run_id = _newest_live_id(ordered)
        self._render_status()

    def _render_status(self) -> None:
        status = self.query_one("#status", Static)
        ordered = _ordered_host_runs(self.snapshot.host_runs)
        if not ordered:
            status.update(WAITING_MESSAGE)
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
        status.update(
            f"Host Run {index + 1}/{len(ordered)} — pid {selected.pid} "
            f"• {repo_name} • {outcome}\n"
            f"{self._render_operational_summary(selected)}\n"
            f"{self._render_resource_bars(selected)}"
        )

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
