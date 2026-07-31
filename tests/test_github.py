"""Behavior tests for optional GitHub issue enrichment."""

from __future__ import annotations

import subprocess
from concurrent.futures import Future
from pathlib import Path

from sandcastle_dashboard.github import (
    GitHubIssue,
    GitHubIssueEnricher,
    lookup_github_issue,
    run_gh_issue_view,
)
from sandcastle_dashboard.snapshot import Castle, HostRun, Repository


def test_run_gh_issue_view_requests_only_title_and_url_in_run_repository(
    tmp_path, monkeypatch
):
    repository = tmp_path / "repository"
    repository.mkdir()
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout='{"title":"Issue title","url":"https://example.test/issues/9"}',
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_gh_issue_view(repository, 9)

    assert result.returncode == 0
    assert captured["command"] == [
        "gh",
        "issue",
        "view",
        "9",
        "--json",
        "title,url",
    ]
    assert captured["cwd"] == repository
    assert captured["shell"] is False


def test_lookup_github_issue_returns_title_and_url_from_successful_gh_response(
    tmp_path,
):
    repository = tmp_path / "repository"
    repository.mkdir()
    calls: list[tuple[object, int]] = []

    def runner(cwd, issue_number):
        calls.append((cwd, issue_number))
        return subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                '{"title":"Enrich focused issues",'
                '"url":"https://github.com/example/project/issues/9"}'
            ),
            stderr="",
        )

    issue = lookup_github_issue(repository, 9, run=runner)

    assert issue is not None
    assert issue.title == "Enrich focused issues"
    assert issue.url == "https://github.com/example/project/issues/9"
    assert calls == [(repository, 9)]


def test_lookup_github_issue_when_gh_is_missing_returns_no_metadata(tmp_path):
    def missing_gh(_cwd, _issue_number):
        raise FileNotFoundError("gh is not installed")

    issue = lookup_github_issue(tmp_path, 9, run=missing_gh)

    assert issue is None


def test_lookup_github_issue_when_gh_is_unavailable_returns_no_metadata(tmp_path):
    def unavailable_gh(_cwd, _issue_number):
        return subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="not authenticated"
        )

    issue = lookup_github_issue(tmp_path, 9, run=unavailable_gh)

    assert issue is None


def test_lookup_github_issue_with_malformed_response_returns_no_metadata(tmp_path):
    def malformed_response(_cwd, _issue_number):
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout="not-json", stderr=""
        )

    issue = lookup_github_issue(tmp_path, 9, run=malformed_response)

    assert issue is None


class ControlledExecutor:
    """Captures one background submission and lets the test complete it."""

    def __init__(self) -> None:
        self.future: Future[GitHubIssue | None] = Future()
        self.submissions: list[tuple[object, tuple[object, ...]]] = []

    def submit(self, function, *args):
        self.submissions.append((function, args))
        return self.future


def test_enrich_schedules_lookup_and_applies_completed_metadata_without_blocking():
    repository = Repository(path="/run/repository", name="repository")
    host_run = HostRun(id="run-1", pid=42, repository=repository)
    castle = Castle(
        name="issue-castle",
        host_run_id="run-1",
        scope="issue",
        issue_number=9,
        vm_state="running",
    )
    executor = ControlledExecutor()

    def lookup(_repository, _issue_number):
        raise AssertionError("the controlled executor must run this asynchronously")

    enricher = GitHubIssueEnricher(lookup=lookup, executor=executor)

    initial = enricher.enrich((castle,), (host_run,))

    assert initial[0].issue_title is None
    assert initial[0].issue_url is None
    assert len(executor.submissions) == 1
    submitted_function, submitted_args = executor.submissions[0]
    assert submitted_function is lookup
    assert submitted_args == (Path(repository.path), 9)

    executor.future.set_result(
        GitHubIssue(
            title="Enrich focused issues",
            url="https://github.com/example/project/issues/9",
        )
    )
    enriched = enricher.enrich((castle,), (host_run,))

    assert enriched[0].issue_title == "Enrich focused issues"
    assert enriched[0].issue_url == "https://github.com/example/project/issues/9"
    assert len(executor.submissions) == 1
