"""Unit tests for dense resource-bar rendering."""

from __future__ import annotations

from sandcastle_dashboard.bars import render_bar


def test_render_bar_is_empty_for_zero_fraction():
    assert render_bar(0.0, width=10) == "░" * 10


def test_render_bar_is_full_for_a_fraction_of_one():
    assert render_bar(1.0, width=10) == "█" * 10


def test_render_bar_fills_proportionally_to_the_fraction():
    assert render_bar(0.5, width=10) == "█" * 5 + "░" * 5


def test_render_bar_clamps_fractions_above_one_to_a_full_bar():
    assert render_bar(2.5, width=10) == "█" * 10


def test_render_bar_clamps_negative_fractions_to_an_empty_bar():
    assert render_bar(-1.0, width=10) == "░" * 10


def test_render_bar_renders_empty_when_fraction_is_unknown():
    assert render_bar(None, width=10) == "░" * 10


def test_render_bar_defaults_to_a_twenty_character_width():
    assert len(render_bar(0.5)) == 20
