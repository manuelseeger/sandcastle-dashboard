"""Console entry point for the ``sandcastle-dashboard`` command."""

from __future__ import annotations

import click

from sandcastle_dashboard.app import DashboardApp
from sandcastle_dashboard.live_snapshot_provider import LiveHostRunSnapshotProvider


@click.command()
def main() -> None:
    """Launch the Sandcastle dashboard."""
    DashboardApp(snapshot_provider=LiveHostRunSnapshotProvider()).run()


if __name__ == "__main__":
    main()
