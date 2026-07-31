"""Console entry point for the ``sandcastle-dashboard`` command."""

from __future__ import annotations

import click

from sandcastle_dashboard.app import DashboardApp
from sandcastle_dashboard.snapshot import Snapshot, SnapshotProvider


class NullSnapshotProvider(SnapshotProvider):
    """Reports that no Host Run exists.

    A placeholder used until host discovery adapters (a later issue) supply a
    real ``SnapshotProvider``.
    """

    def get_snapshot(self) -> Snapshot:
        return Snapshot()


@click.command()
def main() -> None:
    """Launch the Sandcastle dashboard."""
    DashboardApp(snapshot_provider=NullSnapshotProvider()).run()


if __name__ == "__main__":
    main()
