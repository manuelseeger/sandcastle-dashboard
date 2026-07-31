"""Console entry point for the ``sandcastle-dashboard`` command."""

from __future__ import annotations

import click

from sandcastle_dashboard.app import DashboardApp
from sandcastle_dashboard.live_snapshot_provider import LiveHostRunSnapshotProvider


@click.command()
def main() -> None:
    """Launch the Sandcastle dashboard."""
    provider = LiveHostRunSnapshotProvider()
    try:
        DashboardApp(snapshot_provider=provider).run()
    finally:
        provider.close()


if __name__ == "__main__":
    main()
