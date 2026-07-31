"""Unit tests for the dashboard's human-readable formatting helpers."""

from __future__ import annotations

from sandcastle_dashboard.formatting import format_bytes, format_duration


def test_format_duration_shows_seconds_only_under_a_minute():
    assert format_duration(45) == "45s"


def test_format_duration_shows_minutes_and_seconds_under_an_hour():
    assert format_duration(125) == "2m05s"


def test_format_duration_shows_hours_minutes_and_seconds():
    assert format_duration(3725) == "1h02m05s"


def test_format_duration_clamps_negative_durations_to_zero():
    assert format_duration(-5) == "0s"


def test_format_bytes_formats_small_values_in_bytes():
    assert format_bytes(512) == "512.0B"


def test_format_bytes_formats_larger_values_in_binary_units():
    assert format_bytes(1024 * 1024 * 512) == "512.0MiB"


def test_format_bytes_formats_gibibyte_scale_values():
    assert format_bytes(1024**3 * 2) == "2.0GiB"
