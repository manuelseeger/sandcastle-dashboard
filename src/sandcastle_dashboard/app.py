"""The Sandcastle dashboard's Textual application shell."""

from __future__ import annotations

import asyncio
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static

from sandcastle_dashboard.snapshot import Snapshot, SnapshotProvider

WAITING_MESSAGE = (
    "No Host Run detected.\nWaiting for a Sandcastle orchestration run to start..."
)


class DashboardApp(App[None]):
    """Polls an injected ``SnapshotProvider`` and renders dashboard state.

    The first version renders only a waiting state when no Host Run exists;
    later issues add the Host Run selector and Castle grid on top of this
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
    ]

    snapshot: reactive[Snapshot] = reactive(Snapshot(), always_update=True)

    def __init__(
        self,
        snapshot_provider: SnapshotProvider,
        poll_interval: float = 2.0,
    ) -> None:
        super().__init__()
        self._snapshot_provider = snapshot_provider
        self._poll_interval = poll_interval
        self._refresh_in_progress = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="content"):
            yield Static(WAITING_MESSAGE, id="status")
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

    def watch_snapshot(self, snapshot: Snapshot) -> None:
        status = self.query_one("#status", Static)
        if snapshot.host_runs:
            status.update(f"{len(snapshot.host_runs)} Host Run(s) active.")
        else:
            status.update(WAITING_MESSAGE)
