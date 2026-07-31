"""Optional GitHub issue metadata lookup through the authenticated ``gh`` CLI."""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError, Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from sandcastle_dashboard.snapshot import Castle, HostRun


@dataclass(frozen=True, slots=True)
class GitHubIssue:
    """The only remote issue fields retained by the dashboard."""

    title: str
    url: str


IssueRunner = Callable[[Path, int], "subprocess.CompletedProcess[str]"]
IssueLookup = Callable[[Path, int], GitHubIssue | None]


def run_gh_issue_view(
    repository: Path, issue_number: int
) -> subprocess.CompletedProcess[str]:
    """Request only an issue's title and URL from its Run Repository."""
    return subprocess.run(
        [
            "gh",
            "issue",
            "view",
            str(issue_number),
            "--json",
            "title,url",
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
        shell=False,
    )


def lookup_github_issue(
    repository: Path,
    issue_number: int,
    *,
    run: IssueRunner = run_gh_issue_view,
) -> GitHubIssue | None:
    """Return optional issue metadata from an authenticated ``gh`` lookup."""
    try:
        result = run(repository, issue_number)
    except OSError, subprocess.SubprocessError:
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
        title = payload["title"]
        url = payload["url"]
    except json.JSONDecodeError, KeyError, TypeError:
        return None
    if not isinstance(title, str) or not isinstance(url, str) or not title or not url:
        return None
    return GitHubIssue(title=title, url=url)


class GitHubIssueEnricher:
    """Starts optional issue lookups and overlays completed results on Castles.

    ``enrich`` never waits for GitHub. A first call submits missing lookups to
    an executor and returns local Castle state immediately; later calls apply
    completed metadata from the in-memory cache.
    """

    def __init__(
        self,
        lookup: IssueLookup = lookup_github_issue,
        executor: Executor | None = None,
    ) -> None:
        self._lookup = lookup
        self._executor = (
            executor
            if executor is not None
            else ThreadPoolExecutor(
                max_workers=4, thread_name_prefix="sandcastle-github"
            )
        )
        self._owns_executor = executor is None
        self._cache: dict[tuple[str, int], GitHubIssue] = {}
        self._pending: dict[tuple[str, int], Future[GitHubIssue | None]] = {}
        self._unavailable: set[tuple[str, int]] = set()
        self._lock = threading.Lock()

    def enrich(
        self, castles: Sequence[Castle], host_runs: Sequence[HostRun]
    ) -> tuple[Castle, ...]:
        """Return Castles overlaid with any currently cached issue metadata."""
        repositories = {
            host_run.id: host_run.repository.path
            for host_run in host_runs
            if host_run.repository is not None
        }
        enriched: list[Castle] = []
        with self._lock:
            self._collect_finished_locked()
            for castle in castles:
                repository = repositories.get(castle.host_run_id)
                key = (
                    (repository, castle.issue_number)
                    if repository is not None and castle.issue_number is not None
                    else None
                )
                issue = self._cache.get(key) if key is not None else None
                if (
                    key is not None
                    and issue is None
                    and key not in self._pending
                    and key not in self._unavailable
                ):
                    self._pending[key] = self._executor.submit(
                        self._lookup, Path(key[0]), key[1]
                    )
                enriched.append(
                    replace(
                        castle,
                        issue_title=issue.title,
                        issue_url=issue.url,
                    )
                    if issue is not None
                    else castle
                )
        return tuple(enriched)

    def _collect_finished_locked(self) -> None:
        for key, future in tuple(self._pending.items()):
            if not future.done():
                continue
            try:
                issue = future.result()
            except CancelledError:
                issue = None
            if issue is None:
                self._unavailable.add(key)
            else:
                self._cache[key] = issue
            del self._pending[key]

    def close(self) -> None:
        """Release owned worker threads without waiting for active lookups."""
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
