"""Unit tests for role-log selection, run-segmentation, and bounded tails.

Sandcastle role logs are reused across invocations, so the newest
`Run started` marker must gate what is eligible for display, and reads
must stay bounded rather than loading unbounded files.
"""

from __future__ import annotations

import os

from sandcastle_dashboard.logs import (
    latest_run_segment,
    read_bounded_tail,
    resolve_castle_log,
    select_role_log,
    tail_lines,
)
from sandcastle_dashboard.snapshot import Castle


def _castle(scope: str, **kwargs) -> Castle:
    return Castle(
        name="parames-prod-1-x",
        host_run_id="run-1",
        scope=scope,
        vm_state="running",
        **kwargs,
    )


def test_latest_run_segment_keeps_only_content_after_the_last_marker():
    text = "Run started 10:00\nold implementer output\nRun started 10:05\nnew line one\nnew line two"

    segment = latest_run_segment(text)

    assert segment == "Run started 10:05\nnew line one\nnew line two"
    assert "old implementer output" not in segment


def test_latest_run_segment_returns_full_text_when_no_marker_present():
    text = "some line\nanother line"

    assert latest_run_segment(text) == text


def test_tail_lines_returns_only_the_newest_lines():
    text = "\n".join(f"line{i}" for i in range(10))

    assert tail_lines(text, max_lines=3) == ["line7", "line8", "line9"]


def test_tail_lines_returns_everything_when_fewer_lines_than_requested():
    assert tail_lines("a\nb", max_lines=10) == ["a", "b"]


def test_read_bounded_tail_returns_empty_string_for_a_missing_file(tmp_path):
    assert read_bounded_tail(tmp_path / "missing.log") == ""


def test_read_bounded_tail_only_reads_the_trailing_window(tmp_path):
    path = tmp_path / "big.log"
    path.write_text("x" * 100 + "\n" + "y" * 100 + "\n" + "z" * 10)

    tail = read_bounded_tail(path, max_bytes=20)

    assert "x" * 100 not in tail
    assert tail.strip() == "z" * 10


def test_read_bounded_tail_finds_a_marker_that_falls_within_the_window(tmp_path):
    path = tmp_path / "role.log"
    old_segment = "Run started 09:00\n" + ("old\n" * 50)
    new_segment = "Run started 10:00\nnew line\n"
    path.write_text(old_segment + new_segment)

    tail = read_bounded_tail(path, max_bytes=len(new_segment) + 10)
    segment = latest_run_segment(tail)

    assert segment.startswith("Run started 10:00")
    assert "old" not in segment


def test_select_role_log_for_planner_scope_picks_the_newest_planner_log(tmp_path):
    logs_dir = tmp_path
    older = logs_dir / "planner-branch-a-planner.log"
    newer = logs_dir / "planner-branch-b-planner.log"
    older.write_text("old planner log")
    newer.write_text("new planner log")
    _age(older, newer)

    path, phase = select_role_log(logs_dir, _castle("planner"))

    assert phase == "planner"
    assert path == newer


def test_select_role_log_for_merger_scope_matches_the_root_id(tmp_path):
    logs_dir = tmp_path
    (logs_dir / "sandcastle-issue-9-merger-9.log").write_text("merger for issue 9")
    (logs_dir / "sandcastle-issue-3-merger-3.log").write_text("merger for issue 3")

    path, phase = select_role_log(logs_dir, _castle("merger", scope_id="9"))

    assert phase == "merger"
    assert path == logs_dir / "sandcastle-issue-9-merger-9.log"


def test_select_role_log_for_merger_scope_returns_none_when_no_log_exists(tmp_path):
    path, phase = select_role_log(tmp_path, _castle("merger", scope_id="9"))

    assert path is None
    assert phase == "merger"


def test_select_role_log_for_issue_scope_reports_provisioning_before_any_log_exists(
    tmp_path,
):
    path, phase = select_role_log(tmp_path, _castle("issue", issue_number=9))

    assert path is None
    assert phase == "provisioning"


def test_select_role_log_for_issue_scope_identifies_the_implementer_log(tmp_path):
    implementer = tmp_path / "sandcastle-issue-9-implementer-9.log"
    implementer.write_text("implementer output")

    path, phase = select_role_log(tmp_path, _castle("issue", issue_number=9))

    assert path == implementer
    assert phase == "implementer"


def test_select_role_log_for_issue_scope_matches_current_work_branch_filename(tmp_path):
    implementer = tmp_path / "sandcastle-work-issue-39-implementer-39.log"
    implementer.write_text("implementer output")

    path, phase = select_role_log(tmp_path, _castle("issue", issue_number=39))

    assert path == implementer
    assert phase == "implementer"


def test_select_role_log_for_issue_scope_prefers_the_most_recently_active_role(
    tmp_path,
):
    implementer = tmp_path / "sandcastle-issue-9-implementer-9.log"
    reviewer = tmp_path / "sandcastle-issue-9-reviewer-9.log"
    implementer.write_text("implementer output")
    reviewer.write_text("reviewer output")
    _age(implementer, reviewer)

    path, phase = select_role_log(tmp_path, _castle("issue", issue_number=9))

    assert path == reviewer
    assert phase == "reviewer"


def test_select_role_log_ignores_an_older_reviewer_log_from_a_prior_invocation(
    tmp_path,
):
    implementer = tmp_path / "sandcastle-issue-9-implementer-9.log"
    reviewer = tmp_path / "sandcastle-issue-9-reviewer-9.log"
    reviewer.write_text("stale reviewer output from a previous run")
    implementer.write_text("current implementer output")
    _age(reviewer, implementer)

    path, phase = select_role_log(tmp_path, _castle("issue", issue_number=9))

    assert path == implementer
    assert phase == "implementer"


def test_resolve_castle_log_returns_provisioning_with_no_tail_when_logs_dir_is_missing(
    tmp_path,
):
    selection = resolve_castle_log(
        tmp_path / "does-not-exist", _castle("issue", issue_number=9)
    )

    assert selection.phase == "provisioning"
    assert selection.log_tail == ()
    assert selection.last_activity_at is None


def test_resolve_castle_log_returns_the_latest_segment_bounded_to_max_lines(tmp_path):
    path = tmp_path / "sandcastle-issue-9-implementer-9.log"
    old_segment = "Run started 09:00\nold line\n"
    new_lines = ["Run started 10:00" if i == 0 else f"line{i}" for i in range(5)]
    path.write_text(old_segment + "\n".join(new_lines))

    selection = resolve_castle_log(
        tmp_path, _castle("issue", issue_number=9), max_lines=3
    )

    assert selection.phase == "implementer"
    assert selection.log_tail == ("line2", "line3", "line4")
    assert selection.last_activity_at == path.stat().st_mtime


def _age(older_path, newer_path) -> None:
    """Force ``older_path`` to have an earlier mtime than ``newer_path``."""
    now = newer_path.stat().st_mtime
    os.utime(older_path, (now - 10, now - 10))
